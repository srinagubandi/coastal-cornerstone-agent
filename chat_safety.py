import re, unicodedata
from safety import redact, TOKEN

def _clean(value, minimum, maximum):
    if not isinstance(value, str) or len(value) > maximum:
        return None
    allowed = {'\n', '\t', '\r'}
    for c in value:
        cat = unicodedata.category(c)
        if cat in ('Cc', 'Cf', 'Cs') and c not in allowed:
            return None
    value = unicodedata.normalize('NFKC', value)
    value = re.sub(r'\s+', ' ', value).strip()
    if not (minimum <= len(value) <= maximum):
        return None
    if not any(c.isalpha() or c.isdigit() for c in value):
        return None
    return value

NEUTRAL = "Please ask about Coastal Cornerstone Construction and its published company information."
PROHIBITED_DECLINE = "I'm unable to respond to requests regarding race, sex, religion, or political opinions. If you have a construction-related question, I'm happy to help with that."
OFF_TOPIC_DECLINE = "I'm here to help with Coastal Cornerstone Construction's services, projects, and related inquiries. Your question falls outside that scope. If you have a construction-related need, please reach out directly."
HUMAN = 'If you need pricing, scheduling, engineering or specific accessibility details, you can reach us at (727) 771-5672 or email Ben at ben@cccbuild.com. You may also use our contact form at https://cccbuild-website-production.up.railway.app/contact/#contact-title to get in touch.'

tp = TOKEN.pattern.lstrip('(?i)')
CREDENTIAL_PATTERN = re.compile(r'(?i)('+tp+r'|password|credential|api\s+key|secret|access\s+token|bearer\s+token|sk-[a-z0-9_-]+|re_[a-z0-9_-]+|eyJ|BEGIN\s+PRIVATE\s+KEY)', re.IGNORECASE)
INJECTION_PATTERN = re.compile('(ignore|disregard|override).{0,100}(instructions|prompt)|(you are now)|(run|execute).{0,100}(code|script|command)|(reveal|exfiltrate).{0,100}(secret|password|system prompt)|(system|developer).{0,100}(prompt|message|instructions)', re.IGNORECASE)

NSFW_PATTERN = re.compile(r"\b(?:pornography|pornographic|porn|sex|sexual|erotic|nudes|rape|masturbation|exploits|hacking|bombmaking|kill\s*people)\b", re.IGNORECASE)
PRIVATE_DATA_PATTERN = re.compile(r"\b(?:customer\s*records?|private\s*records?|private\s*data|CRM|credit\s*cards?|social\s*security)\b", re.IGNORECASE)
OFFTOPIC_PATTERN = re.compile('(?i)\\b(sports?|football|bitcoins?|cryptocurrenc(y|ies)?|cryptos?|politics?|jokes?|recipes?|videogames?|poems?|homework|calculuses?)\\b', re.IGNORECASE)

import re

BUSINESS_PATTERN = re.compile('(?:\\b(company|coastal|cornerstone|construction|build|building|home|house|residential|commercial|icf|concrete|insulation|hurricane|project|contractor|service|contact|location|florida|pool|remodel|permit|engineering|warranty|price|pricing|cost|quote|accessibility|team|business|phone|email|hours|areas|serve|serving|counties|license|licensed|WOSB|women-owned|BBB|hurricanes|storms|wind|flood|insurance|pilings|mold|energy|noise|maintenance|benefits|Hillsborough|Pinellas|Pasco|Hernando|Citrus)s?\\b)|(?:\\b(subcontractor|subcontractors|architect|architects|engineer|engineers|text|texting|call|calling|capability statement|capability statements|bonding|bond|bonded|capacity)\\b)', re.IGNORECASE)

HUMAN_TRIGGER_PATTERN = re.compile(r'\b(quote|quotation)s?\b|\b(price|cost)s?\b|\b(pricing|estimate)s?\b|\b(engineering|warranty|warranties)\b|\b(structural calculation)s?\b|\b(load[ -]bearing)\b|\b(availability|available|booking|book|schedule|scheduling)\b', re.IGNORECASE)

GENERAL_COMPANY_PATTERN = re.compile('\\b(?:ccc|address|located|based|portfolio|owner|ownership|experience|renovations|kitchen|bathroom|how\\s+long\\s+have\\s+you\\s+been\\s+doing\\s+this|what\\s+do\\s+you\\s+do|where\\s+(?:do\\s+you\\s+work|do\\s+you\\s+build)|what\\s+counties\\s+do\\s+you\\s+cover)\\b', re.IGNORECASE)
HUMAN_HELP_PATTERN = re.compile('\\b(?:I need more help|can I talk to someone|can I speak to Ben|please call me)\\b', re.IGNORECASE)

CONSTRUCTION_TOPIC_PATTERN = re.compile('(?i)\\b(builders?|foundations?|framing|roofs?|roofing|walls?|drywall|cements?|materials?|windows?|doors?|plumbings?|electrical|HVAC|carpentry)\\b', re.IGNORECASE)
STRUCTURAL_HELP_PATTERN = re.compile('\\b(structural\\s+(loads|calculations)|design\\b.*\\bload-bearing)\\b', re.IGNORECASE)

def screen_message(body):
    try:
        if not isinstance(body, dict) or set(body.keys()) != {'message'} or not isinstance(body['message'], str):
            return ('invalid', '')
        raw = _clean(body['message'], 2, 1500)
        if raw is None:
            return ('invalid', '')
        from safety import classify_question, sanitize_question
        kind, _reason = classify_question(raw)
        if kind == 'blocked':
            return ('blocked', '')
        if kind not in ('human', 'safe'):
            return ('invalid', '')
        import re
        cleaned = sanitize_question(raw)
        if not cleaned or len(cleaned) < 2 or len(cleaned) > 1500 or not re.search(r'[A-Za-z]', cleaned):
            return ('invalid', '')
        return (kind, cleaned)
    except Exception:
        return ('invalid', '')

import re
import unicodedata

def validate_contact(body):
    if not isinstance(body, dict):
        return None, 'invalid_contact'
    
    required_keys = {'name', 'email', 'phone', 'message', 'website'}
    if set(body) != required_keys:
        return None, 'invalid_contact'
        
    name = body['name']
    email = body['email']
    phone = body['phone']
    message = body['message']
    website = body['website']
    
    if not all(isinstance(x, str) for x in [name, email, phone, message, website]):
        return None, 'invalid_contact'
        
    if website != '':
        return None, 'invalid_contact'
        
    def has_bad_unicode(s):
        for c in s:
            if unicodedata.category(c) in ('Cc', 'Cf', 'Cs'):
                return True
        return False
        
    def contains_url(s):
        return ('http://' in s or 'https://' in s or 'www.' in s)
        
    def matches_patterns(s):
        return (CREDENTIAL_PATTERN.search(s) or
                INJECTION_PATTERN.search(s) or
                NSFW_PATTERN.search(s) or
                PRIVATE_DATA_PATTERN.search(s) or
                OFFTOPIC_PATTERN.search(s))
                
    # Check raw inputs before cleaning
    for field in [name, email, phone]:
        if has_bad_unicode(field) or contains_url(field) or matches_patterns(field):
            return None, 'blocked'
            
    # Validate name
    name = _clean(name, 1, 100)
    if name is None:
        return None, 'invalid_contact'
    if not (1 <= len(name) <= 100):
        return None, 'invalid_contact'
    if not re.search(r'[a-zA-Z]', name):
        return None, 'invalid_contact'
    if not all(unicodedata.category(c) in ('Ll','Lu','Lt','Lm','Lo') or c in " .-'" for c in name):
        return None, 'invalid_contact'
        
    # Validate email
    email = email.strip().lower()
    if len(email) > 254:
        return None, 'invalid_contact'
    if email.count('@') != 1:
        return None, 'invalid_contact'
    local, domain = email.split('@')
    if not re.fullmatch(r'[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&\'*+/=?^_`{|}~-]+)*', local):
        return None, 'invalid_contact'
    if '..' in local or local.startswith('.') or local.endswith('.'):
        return None, 'invalid_contact'
    labels = domain.split('.')
    if len(labels) < 2:
        return None, 'invalid_contact'
    for i, label in enumerate(labels):
        if not (1 <= len(label) <= 63):
            return None, 'invalid_contact'
        if label.startswith('-') or label.endswith('-'):
            return None, 'invalid_contact'
        if not re.fullmatch(r'[a-zA-Z0-9-]+', label):
            return None, 'invalid_contact'
        if i == len(labels)-1 and not re.fullmatch(r'[a-zA-Z][a-zA-Z-]*[a-zA-Z]', label):
            return None, 'invalid_contact'
            
    # Validate phone
    if len(phone) > 40:
        return None, 'invalid_contact'
    cleaned_phone = re.sub(r'[^0-9]', '', phone)
    if not (10 <= len(cleaned_phone) <= 15):
        return None, 'invalid_contact'
        
    # Validate message
    kind, safe_message = screen_message({'message': message})
    if kind not in ('safe', 'human'):
        return None, 'spam'
        
    return {
        'name': name,
        'email': email,
        'phone': cleaned_phone,
        'message': safe_message
    }, None
