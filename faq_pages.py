"""Public FAQ HTML/JSON page rendering – no I/O, no network, pure string rendering."""
import html
from urllib.parse import urlparse

# trusted hosts for source label extraction
SITE_HOSTS = frozenset({"cccbuild.com", "www.cccbuild.com", "cccbuild-3mhyn4jl.manus.space"})

PATH_LABELS = {
    '/': 'Company information',
    '/commercial/': 'Commercial construction',
    '/residential/': 'Residential construction',
    '/icf/': 'ICF construction',
    '/process/': 'Our process',
    '/about/': 'About Coastal Cornerstone',
    '/contact/': 'Contact Coastal Cornerstone',
    '/projects/': 'Project gallery',
    '/resources/': 'Resources',
    '/services/': 'Commercial construction',
    '/about-us/': 'About Coastal Cornerstone',
    '/contact-us/': 'Contact Coastal Cornerstone',
}


def _label_for_url(url_str):
    """Return a human-readable label for a source URL, or empty string."""
    try:
        parsed = urlparse(url_str)
        if parsed.scheme not in ('http', 'https'):
            return ''
        if parsed.hostname in SITE_HOSTS:
            return PATH_LABELS.get(parsed.path, parsed.hostname)
        return parsed.hostname or 'external site'
    except Exception:
        return ''


def source_citation(url_str):
    if not url_str:
        return ''
    label = _label_for_url(url_str)
    if not label:
        return ''
    safe_url = html.escape(url_str)
    safe_label = html.escape(label)
    return f'<a href="{safe_url}">Source: {safe_label} ↗</a>'


def render_faq_html(faq, config):
    q = html.escape(faq['question'])
    a_lines = html.escape(faq['answer']).split('\n')
    answer_html = '<br>\n'.join(a_lines)
    citation = source_citation(faq['source_urls'][0] if faq['source_urls'] else '')
    origin = html.escape(config.public_origin or "", quote=True)
    canonical = f'{origin}/faq/{html.escape(faq["id"])}' if origin else f'/faq/{html.escape(faq["id"])}'
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Coastal Cornerstone Construction FAQ: {q}">
  {'<link rel="canonical" href="' + canonical + '">' if config.public_origin else ''}
  <title>{q} - Coastal Cornerstone Construction</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  <a class="skip" href="#main">Skip to content</a>
  <header class="topbar">
    <a class="brand" href="/docs">Coastal <span>Cornerstone</span><small>PUBLIC INFORMATION AGENT</small></a>
    <nav aria-label="Public navigation">
      <a href="https://cccbuild-3mhyn4jl.manus.space/faq/">Curated FAQs</a>
      <a href="/openapi.json">OpenAPI</a>
      <a href="/agent-card.json">Discovery</a>
    </nav>
  </header>
  <main id="main" class="docs">
    <article class="panel">
      <h1>{q}</h1>
      <div class="faq-answer">{answer_html}</div>
      <p class="faq-source">{citation}</p>
    </article>
    <footer>
      <p><a href="https://cccbuild-3mhyn4jl.manus.space/faq/">View all FAQs</a> · <a href="/docs">Agent documentation</a> · <a href="https://cccbuild-3mhyn4jl.manus.space">Company website ↗</a></p>
    </footer>
  </main>
</body>
</html>'''

def render_faq_error(status, config):
    """Render a generic error page for 400/404 without echoing any user input."""
    heading = "FAQ not found" if status == 404 else "Invalid request"
    message = "The requested FAQ record could not be found." if status == 404 else "The request contains unexpected parameters."
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>{heading} - Coastal Cornerstone Construction</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  <a class="skip" href="#main">Skip to content</a>
  <header class="topbar">
    <a class="brand" href="/docs">Coastal <span>Cornerstone</span><small>PUBLIC INFORMATION AGENT</small></a>
    <nav aria-label="Public navigation">
      <a href="https://cccbuild-3mhyn4jl.manus.space/faq/">Curated FAQs</a>
      <a href="/openapi.json">OpenAPI</a>
      <a href="/agent-card.json">Discovery</a>
    </nav>
  </header>
  <main id="main" class="docs">
    <section class="panel">
      <h1>{heading}</h1>
      <p>{message} Please browse the <a href="https://cccbuild-3mhyn4jl.manus.space/faq/">full FAQ list</a> or visit the <a href="https://cccbuild-3mhyn4jl.manus.space">company website</a>.</p>
      <p>Contact: <a href="https://cccbuild-3mhyn4jl.manus.space/contact/">company contact page ↗</a></p>
    </section>
  </main>
</body>
</html>'''

def render_faq_404(not_found_id, config):
    """Convenience wrapper for 404 errors."""
    return render_faq_error(404, config)
