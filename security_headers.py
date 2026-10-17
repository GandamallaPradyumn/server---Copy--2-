# security_headers.py
import tornado.web

_headers_applied = False

def apply_security_headers():
    """
    Injects mandatory HTTP security headers into Tornado server handlers.
    Fulfills TSOC Security Requirements S.No 5 (Security Headers) and S.No 6 (Clickjacking Protection).
    """
    global _headers_applied
    if _headers_applied:
        return

    old_set_default_headers = tornado.web.RequestHandler.set_default_headers

    def custom_set_default_headers(self):
        old_set_default_headers(self)
        # S.No 6: Clickjacking Protection
        self.set_header("X-Frame-Options", "SAMEORIGIN")
        
        # S.No 5: Security Headers
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
        self.set_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; frame-ancestors 'self';")
        self.set_header("X-XSS-Protection", "1; mode=block")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")

    tornado.web.RequestHandler.set_default_headers = custom_set_default_headers
    _headers_applied = True
    print("[INFO] Security Headers Patch Applied Successfully (HSTS, X-Frame-Options, CSP, nosniff).")
