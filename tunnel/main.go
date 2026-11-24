// liuli-tunnel is the single-file Go supervisor/proxy for LiuliDNS.
//
// One process supervises one cloudflared Tunnel token and one local reverse
// proxy. All hostnames for the user are mapped to their origin URLs here, so
// all domains share one Tunnel. The proxy counts in-flight requests and
// applies the soft free-plan guard (warn at 800, reject at 1000 by default).
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

type Config struct {
	Cloudflared      string `json:"cloudflared"`
	TokenFile        string `json:"token_file"`
	ProxyListen      string `json:"proxy_listen"`
	ControlListen    string `json:"control_listen"`
	DomainsFile      string `json:"domains_file"`
	StateDir         string `json:"state_dir"`
	WarnConnections  int    `json:"warn_connections"`
	MaxConnections   int    `json:"max_connections"`
	RestartLimit     int    `json:"restart_limit"`
}

type Domain struct {
	Hostname string `json:"hostname"`
	Upstream string `json:"upstream"`
}

type DomainFile struct {
	Domains []Domain `json:"domains"`
}

type Supervisor struct {
	cfg      Config
	logger   *log.Logger
	mu       sync.RWMutex
	domains  map[string]*url.URL
	active   atomic.Int64
	total    atomic.Int64
	warn     atomic.Bool
	tunnelMu sync.Mutex
	proc     *exec.Cmd
	procPID  int
	restarts int
	lastErr  string
	stopped  bool
}

func loadConfig(path string) (Config, error) {
	var c Config
	data, err := os.ReadFile(path)
	if err != nil {
		return c, err
	}
	if err := json.Unmarshal(data, &c); err != nil {
		return c, err
	}
	if c.ProxyListen == "" || c.ControlListen == "" {
		return c, errors.New("proxy_listen and control_listen are required")
	}
	if c.WarnConnections <= 0 {
		c.WarnConnections = 800
	}
	if c.MaxConnections <= 0 {
		c.MaxConnections = 1000
	}
	if c.RestartLimit <= 0 {
		c.RestartLimit = 20
	}
	return c, nil
}

func loadDomains(path string) (map[string]*url.URL, error) {
	out := make(map[string]*url.URL)
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return out, nil
	}
	if err != nil {
			return nil, err
	}
	var f DomainFile
	if err := json.Unmarshal(data, &f); err != nil {
		return nil, err
	}
	for _, d := range f.Domains {
		host := strings.ToLower(strings.TrimSuffix(strings.TrimSpace(d.Hostname), "."))
		if host == "" {
			continue
		}
		u, err := url.Parse(d.Upstream)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			continue
		}
		out[host] = u
	}
	return out, nil
}

func (s *Supervisor) reloadDomains() error {
	d, err := loadDomains(s.cfg.DomainsFile)
	if err != nil {
		s.setError(err.Error())
		return err
	}
	s.mu.Lock()
	s.domains = d
	s.mu.Unlock()
	return nil
}

func (s *Supervisor) setError(msg string) {
	s.tunnelMu.Lock()
	s.lastErr = msg
	s.tunnelMu.Unlock()
}

func (s *Supervisor) proxyHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host := strings.ToLower(strings.TrimSuffix(strings.Split(r.Host, ":")[0], "."))
		s.mu.RLock()
		upstream, ok := s.domains[host]
		s.mu.RUnlock()
		if !ok {
			http.Error(w, "domain not configured on this tunnel", http.StatusNotFound)
			return
		}
		active := s.active.Add(1)
		defer s.active.Add(-1)
		s.total.Add(1)
		if active >= int64(s.cfg.MaxConnections) {
			s.warn.Store(true)
			w.Header().Set("Retry-After", "30")
			http.Error(w, "tunnel concurrency limit reached; retry later", http.StatusServiceUnavailable)
			return
		}
		if active >= int64(s.cfg.WarnConnections) {
			s.warn.Store(true)
			w.Header().Set("X-Liuli-Tunnel-Warning", "connection count high")
		} else {
			s.warn.Store(false)
		}

		rp := httputil.NewSingleHostReverseProxy(upstream)
		orig := rp.Director
		rp.Director = func(req *http.Request) {
			orig(req)
			req.Host = r.Host
			req.Header.Set("X-Forwarded-Host", r.Host)
			req.Header.Set("X-Forwarded-Proto", "https")
		}
		rp.ErrorHandler = func(rw http.ResponseWriter, req *http.Request, err error) {
			s.logger.Printf("proxy upstream error host=%s err=%v", host, err)
			http.Error(rw, "origin unavailable", http.StatusBadGateway)
		}
		rp.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), ctxKeyHost{}, host)))
	})
}

type ctxKeyHost struct{}

func (s *Supervisor) status() map[string]any {
	s.tunnelMu.Lock()
	pid := s.procPID
	lastErr := s.lastErr
	restarts := s.restarts
	s.tunnelMu.Unlock()
	active := s.active.Load()
	total := s.total.Load()
	configured := false
	if token, err := os.ReadFile(s.cfg.TokenFile); err == nil {
		configured = strings.TrimSpace(string(token)) != ""
	}
	s.mu.RLock()
	domainCount := len(s.domains)
	s.mu.RUnlock()
	return map[string]any{
		"configured":        configured,
		"running":           pid > 0,
		"pid":               pid,
		"active_connections": active,
		"total_requests":    total,
		"warn_connections":  s.cfg.WarnConnections,
		"max_connections":   s.cfg.MaxConnections,
		"warning":           active >= int64(s.cfg.WarnConnections),
		"domain_count":      domainCount,
		"restarts":          restarts,
		"last_error":        lastErr,
	}
}

func (s *Supervisor) controlHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"ok":true}`)
	})
	mux.HandleFunc("/status", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(s.status())
	})
	mux.HandleFunc("/reload", func(w http.ResponseWriter, _ *http.Request) {
		if err := s.reloadDomains(); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			_, _ = io.WriteString(w, `{"ok":false}`)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"ok":true}`)
	})
	return mux
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func (s *Supervisor) supervise(ctx context.Context) {
	s.tunnelMu.Lock()
	if s.stopped {
		s.tunnelMu.Unlock()
		return
	}
	s.tunnelMu.Unlock()
	if s.cfg.Cloudflared == "" || !fileExists(s.cfg.Cloudflared) {
		s.setError("cloudflared binary missing")
		return
	}
	token, err := os.ReadFile(s.cfg.TokenFile)
	if err != nil || strings.TrimSpace(string(token)) == "" {
		s.setError("tunnel token missing")
		return
	}
	backoff := 3 * time.Second
	for attempt := 0; attempt < s.cfg.RestartLimit; attempt++ {
		if ctx.Err() != nil {
			return
		}
		logFile, err := os.OpenFile(filepath.Join(s.cfg.StateDir, "cloudflared.log"),
			os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
		if err != nil {
			s.setError("cannot open cloudflared log")
			return
		}
		cmd := exec.CommandContext(ctx, s.cfg.Cloudflared, "tunnel", "--no-autoupdate", "run")
		cmd.Env = append(os.Environ(), "TUNNEL_TOKEN="+strings.TrimSpace(string(token)))
		cmd.Stdout = logFile
		cmd.Stderr = logFile
		if err := cmd.Start(); err != nil {
			_ = logFile.Close()
			s.setError("cloudflared start failed: " + err.Error())
			time.Sleep(backoff)
			continue
		}
		s.tunnelMu.Lock()
		s.proc = cmd
		s.procPID = cmd.Process.Pid
		s.lastErr = ""
		s.restarts = attempt
		s.tunnelMu.Unlock()
		s.logger.Printf("cloudflared started pid=%d attempt=%d", cmd.Process.Pid, attempt)
		err = cmd.Wait()
		_ = logFile.Close()
		s.tunnelMu.Lock()
		s.proc = nil
		s.procPID = 0
		s.tunnelMu.Unlock()
		if ctx.Err() != nil {
			return
		}
		s.setError(fmt.Sprintf("cloudflared exited: %v", err))
		s.logger.Printf("cloudflared exited err=%v; retrying in %s", err, backoff)
		time.Sleep(backoff)
		if backoff < 30*time.Second {
			backoff *= 2
		}
	}
	s.setError("cloudflared restart limit reached")
}

func main() {
	if len(os.Args) < 3 || os.Args[1] != "run" || os.Args[2] != "--config" || len(os.Args) < 4 {
		fmt.Fprintln(os.Stderr, "usage: liuli-tunnel run --config <json>")
		os.Exit(2)
	}
	cfg, err := loadConfig(os.Args[3])
	if err != nil {
		fmt.Fprintln(os.Stderr, "config error:", err)
		os.Exit(2)
	}
	if cfg.StateDir == "" {
		cfg.StateDir = "."
	}
	logPath := filepath.Join(cfg.StateDir, "tunnel.log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		fmt.Fprintln(os.Stderr, "log error:", err)
		os.Exit(2)
	}
	defer logFile.Close()
	logger := log.New(logFile, "liuli-tunnel ", log.LstdFlags|log.LUTC)
	s := &Supervisor{cfg: cfg, logger: logger, domains: map[string]*url.URL{}}
	if err := s.reloadDomains(); err != nil {
		logger.Printf("initial domains unavailable: %v", err)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.Signal(15))
	defer cancel()

	proxySrv := &http.Server{Addr: cfg.ProxyListen, Handler: s.proxyHandler()}
	controlSrv := &http.Server{Addr: cfg.ControlListen, Handler: s.controlHandler()}
	go func() {
		logger.Printf("proxy listening on %s", cfg.ProxyListen)
		if err := proxySrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Printf("proxy error: %v", err)
			cancel()
		}
	}()
	go func() {
		logger.Printf("control listening on %s", cfg.ControlListen)
		if err := controlSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Printf("control error: %v", err)
			cancel()
		}
	}()
	go s.supervise(ctx)
	go func() {
		ticker := time.NewTicker(2 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				_ = s.reloadDomains()
			}
		}
	}()

	<-ctx.Done()
	shutdownCtx, stop := context.WithTimeout(context.Background(), 5*time.Second)
	defer stop()
	_ = proxySrv.Shutdown(shutdownCtx)
	_ = controlSrv.Shutdown(shutdownCtx)
	s.tunnelMu.Lock()
	if s.proc != nil && s.proc.Process != nil {
		_ = s.proc.Process.Signal(syscall.Signal(15))
	}
	s.stopped = true
	s.tunnelMu.Unlock()
	logger.Printf("stopped")
}
