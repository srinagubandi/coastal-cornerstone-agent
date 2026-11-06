"""Basic data minimization, not a promise of anonymity or complete PII detection."""
import ipaddress
import re
import unicodedata

EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>]+")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
TOKEN = re.compile(r"(?i)\b(?:sk-[a-z0-9_-]{8,}|re_[a-z0-9_-]{8,}|bearer\s+\S+|(?:api[_ -]?key|password|secret)\s*[:=]\s*\S+)")
IP_CANDIDATE = re.compile(r"(?<![\w])(?:\[)?[A-Fa-f0-9:.]+(?:\])?(?:%[\w.-]+)?(?!\w)")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
UNSUPPORTED = re.compile(r"(?i)\b(?:quotes?|quotations?|prices?|pricing|cost estimate|warrant(?:y|ies)|availability|available (?:today|now)|engineering|structural calculations?|load bearing|customer records?|crm|private (?:data|records)|exploit|hack|ignore (?:all |previous )?instructions|system prompt|execute|book(?:ing)?|schedule (?:a|my)|send (?:an? )?email|credit card|social security)\b")

CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(?:password|credential|api[ _-]?key|secret|access[ _-]?token|bearer[ _-]?token|"
    r"sk-[a-z0-9_-]+|re_[a-z0-9_-]+|eyJ|BEGIN\s+PRIVATE\s+KEY)\b"
)
INJECTION_PATTERN = re.compile(
    r"(?i)(?:\b(?:ignore|disregard|override)\b.{0,100}\b(?:instructions?|prompts?|system[ \t-]*prompt|developer[ \t-]*prompt)\b)|"
    r"(?:\b(?:run|execute)\b.{0,80}\b(?:code|script|command)\b)|"
    r"(?:\b(?:reveal|exfiltrate|print|display|show|tell)\b.{0,100}\b(?:secret|password|system[ \t-]*prompt|developer[ \t-]*prompt)\b)|"
    r"(?:\b(?:system|developer)[ \t-]*(?:prompt|message|instruction)\b)|"
    r"\bdo not follow previous\b|\bjailbreak\b",
    re.IGNORECASE | re.DOTALL,
)
PRIVATE_DATA_PATTERN = re.compile(
    r"(?i)\b(?:customer\s*records?|private\s*records?|private\s*data|crm|"
    r"credit\s*card|cvv|social\s*security|medical\s*records?|personally\s*identifiable)\b"
)
PRIVATE_URL_PATTERN = re.compile(
    r"(?i)\b(?:private|internal|secret|admin|hidden|unlisted|password[ -]protected)\s+(?:url|link|endpoint|webhook)|"
    r"\b(?:webhook|endpoint)\b.{0,40}\b(?:url|http)"
)
NSFW_PATTERN = re.compile(
    r"(?i)\b(?:porn(?:ography|ographic)?|erotic|nudes?|nude\s+photos?|masturbation|"
    r"rape|sexual\s+(?:assault|abuse|intercourse|contact)|sexually\s+explicit|"
    r"fetish|escort|prostitut(?:e|ion)|brothel|orgy|incest|pedophil|bestiality)\b"
)
OFFTOPIC_PATTERN = re.compile(
    r"(?i)\b(?:sports\s+(?:debate|betting)|football\s+(?:game|score)|bitcoin|cryptocurrenc(?:y|ies)|cryptos?|"
    r"politics?|jokes?|recipes?|videogames?|poems?|homework|calculus)\b"
)
HATE_DISCRIMINATION_PATTERN = re.compile(
    r"(?i)"
    r"(?:\b(?:hate|despise|can'?t\s+stand|don'?t\s+(?:trust|like|want)|do\s+not\s+(?:trust|like|want))\b.{0,60}\b(?:"
    r"(?:black|african|white|hispanic|latino|asian|middle[ -]eastern)\s+(?:people|persons?|workers?|employees?|customers?|clients?|community|communities|immigrants?|muslims?|christians?|jews?|men|women|disabled|elderly|indigenous)"
    r"|blacks|whites|africans?|hispanics?|latinos?|asians?|middle[ -]easterners?"
    r"|muslims?|jews?|christians?|women|woman|men|man|disabled|gay|lesbian|bisexual|transgender|elderly|indigenous|immigrants?"
    r")\b)"
    r"|(?:\b(?:"
    r"(?:black|african|white|hispanic|latino|asian|middle[ -]eastern)\s+(?:people|persons?|workers?|employees?|customers?|clients?|community|communities|immigrants?|muslims?|christians?|jews?|men|women|disabled|elderly|indigenous)"
    r"|blacks|whites|africans?|hispanics?|latinos?|asians?|middle[ -]easterners?"
    r"|muslims?|jews?|christians?|women|woman|men|man|disabled|gay|lesbian|bisexual|transgender|elderly|indigenous|immigrants?"
    r")\b"
        r".{0,80}\b(?:inferior|superior|stupid|lazy|evil|disgusting|unfit|violent|terrorists?|dishonest|"
        r"should(?:n'?t| not)\s+(?:be|belong)|don'?t\s+belong|do\s+not\s+belong|not\s+(?:capable|qualified|welcome|allowed)|"
        r"cannot?\s+work|cannot?\s+do)\b)"
    r"|(?:\b(?:racist|sexist|homophobic|transphobic|antisemitic|islamophobic|white\s+supremac|hate\s+speech)\b"
    r".{0,40}\b(?:against|targeting|slur|remark|violence|attack)\b)"
)

SLUR_PATTERN = re.compile(
    r"(?i)\b(?:nigger|nigga|faggot|fag|kike|spic|chink|gook|wetback|tranny|retard|raghead|coon|dyke|whore|slut)(?:s|es)?\b"
)

VIOLENCE_VERB = r"\b(?:kill|murder|shoot|beat|exterminate|slaughter|assault|execute|massacre|attack)(?:s|es|ed|ing)?\b"
PROTECTED_TARGET = (
    r"\b(?:"
    r"(?:black|white|african|hispanic|latino|asian|middle[ -]eastern)\s+"
    r"(?:people|persons?|workers?|employees?|customers?|clients?|community|communities|"
    r"immigrants?|muslims?|christians?|jews?|men|women|disabled|elderly|indigenous)"
    r"|(?:blacks|whites|africans?|hispanics?|latinos?|asians?|middle[ -]easterners?)"
    r"|muslims?|jews?|christians?|women|woman|men|man|disabled|gay|lesbian|bisexual|"
    r"transgender|elderly|indigenous|immigrants?"
    r")\b"
)
EXPLICIT_VIOLENCE_PROTECTED_PATTERN = re.compile(
    VIOLENCE_VERB + r"[^.!?\n]{0,80}?" + PROTECTED_TARGET,
    re.IGNORECASE
)

LEGIT_SEXUAL_CONSTRUCTION_PATTERN = re.compile(
    r"(?i)"
    r"\bsex[\s-]?(?:bolts?|segregated|separated|partition|restroom|facilities?)\b"
    r"|\b(?:male|female)[\s-]*(?:plumbing|pipe|fitting|thread(?:ed)?|adapter|connector|nipple|valve)\b"
    r"|\b(?:restroom|bathroom|toilet|locker)[\s-]*(?:layout|partition|separat|sex|gender)[\s-]*(?:separated|divided|arrangement|layout)?\b"
    r"|\b(?:men'?s|women'?s|gender-neutral|unisex|sex-separated)\s+(?:restroom|bathroom|toilet|locker|facilit(?:y|ies))\b"
)
RELIGIOUS_POLITICAL_DEBATE_PATTERN = re.compile(
    r"(?i)\b(?:political\s+debate|religious\s+debate|democrats?|republicans?|presidential\s+election|"
    r"campaign\s+season|partisan\s+politics|abortion|gun\s+control|immigration\s+policy|tax\s+policy|"
    r"who\s+should\s+be\s+president|vote\s+for\s+president|political\s+(?:opinion|view|stance|party|candidate|ideology)|"
    r"religion\s+(?:vs|versus|better|right|wrong|true|false|opinion|view|stance|belief)|"
    r"theology|afterlife|salvation|proselytize|atheism|god'?s?\s+existence|"
    r"sectarian\s+(?:violence|conflict|debate)|"
    r"(?:christianity|islam|judaism|buddhism|hinduism)\s+is\s+(?:the\s+)?(?:one\s+true|only\s+true|true|only|right)\s+(?:faith|religion|way|path|belief))\b"
)
CONSTRUCTION_CONTEXT_PATTERN = re.compile('(?:(?:(?:\\b(?:construction|contractor|contractors|subcontractor|subcontractors|builder|builders|build|building|buildings|home|homes|house|houses|residential|commercial|icf|concrete|insulation|hurricane|hurricanes|remodel|remodeling|renovation|renovations|roof|roofs|roofing|framing|foundation|foundations|drywall|plumbing|electrical|hvac|carpentry|windows?|doors?|walls?|materials?|cements?|floors|flooring|ceilings|paint|moisture|condensation|permit|permits|accessibility|accessible|ada|pool|pools|mold|energy|noise|maintenance|benefits|counties|county|license|licensed|wosb|women-owned|bbb|insurance|process|processes|estimate|estimates|estimating|quote\\s+process|free\\s+estimate|pilings|wind|flood|storm|storms|team|business|company|coastal|cornerstone|ccc|address|located|based|portfolio|owner|ownership|experience|kitchen|kitchens|bathroom|bathrooms|shower|showers|ramp|ramps|layout|layouts|how long have you been doing this|what do you do|where do you work|where do you build|what counties do you cover|contact|phone|email|hours|areas|serve|serving|architect|architects|engineer|engineers|capability statement|bonding|bond|bonded|capacity|sex bolt|sex-separated|male plumbing|female plumbing|raceway|church|mosque|temple|synagogue|bedroom|dimensions|pump|pumps|kill[ -]?switch(?:es)?|emergency[ -]?stop(?:s)?)\\b|\\b(?:construction|build(?:ing)?|remodel|renovation|home|house|commercial)\\s+project\\b|\\bhow\\s+(?:long\\s+have\\s+you\\s+been\\s+doing\\s+this|do\\s+you\\s+plan\\s+a\\s+schedule|do\\s+you\\s+estimate\\s+costs|determine\\s+pricing)\\b)|\\b(?:seat|seats|raised seat|raised seats|stair|stairs|grab bar|grab bars|deep squat|deep squats)\\b)|(?:(?:scope\\s+is\\s+defined|scope\\s+defined|project-specific\\s+review|site\\s+conditions|access\\s+needs)))|(?:\\bproject[-\\s]scope\\b)', 34)
SAFE_PROCESS_PATTERN = re.compile(
    r"(?i)\b(?:"
    r"pricing\s+(?:factors?|considerations?|variables?|process|structure|methodology|breakdown)"
    r"|cost\s+(?:factors?|drivers?|considerations?|process|breakdown)"
    r"|estimate\s+(?:process|methodology|factors?|considerations?)|estimating\s+(?:process|methodology)|quote\s+process"
    r"|schedule\s+planning"
    r"|factors?\s+(?:influencing|affecting|driving)\s+(?:pricing|cost|estimated?|schedule)"
    r")"
    r"|\bhow\s+(?:do|does)\s+(?:you|the\s+team|coastal|cornerstone)\s+(?:estimate|price|plan\s+schedules?|determine\s+pricing|build\s+(?:a\s+)?schedule)\b"
)

ACCESSIBILITY_HUMAN_PATTERN = re.compile(
    r"(?i)\b(?:accessibility|accessible|ada|disabled\s+access|elderly\s+access|wheelchair\s+access|mobility\s+access)\b"
    r"|\b(?:disabled|elderly|wheelchair|mobility)[^.!?\n]{0,80}\b(?:access|safe|safer|ramps?|lifts?|grab\s+bars?|walk[-\s]in\s+showers?|roll[-\s]in\s+showers?|barrier[-\s]free\s+showers?|bathing|showers?|seats?|stairs?)\b"
    r"|\b(?:ramps?|lifts?|grab\s+bars?|walk[-\s]in\s+showers?|roll[-\s]in\s+showers?|barrier[-\s]free\s+showers?|shower\s+seats?|bath\s+seats?|raised\s+seats?)\b"
    r"|\b(?:showers?|bathing|seats?|stairs?)\s+(?:layout|layouts|design|designs|placement|configuration)\b"
    r"|\b(?:layout|layouts|design|designs|placement|configuration)\s+(?:of|for)\s+(?:a\s+|an\s+|the\s+)?(?:showers?|bathing|seats?|stairs?)\b"
    r"|\b(?:design|designing|layout|laying\s+out|place|placing|configure|configuring)\s+(?:a\s+|an\s+|the\s+)?(?:showers?|bathing|seats?|stairs?)\b"
    r"|\b(?:bathing|showers?|seats?|stairs?)\s+(?:option|options|choice|choices)\b"
    r"|\b(?:safe|safer|safest)\s+(?:bathing|shower|showers|stairs?|seat|seats)\s+(?:option|options|choice|choices|design|layout)\b"
)
SAFETY_DIMENSION_HUMAN_PATTERN = re.compile(
    r"(?i)\b(?:project[-\s]specific|site[-\s]specific|specific\s+(?:project|site)\s+(?:advice|question|questions|review)|safety\s+(?:determination|determinations|assessment|assessments|evaluation|evaluations|concern|concerns|question|questions)|dimensions?|dimensional|measurements?|clearances?|doorway\s+width|hallway\s+width|turning\s+radius|weight\s+capacity|load\s+capacity|weight\s+limit|how\s+much\s+weight)\b"
    r"|\b(?:ramp|shower|seat|stairs?|doorway|hallway|bathroom|toilet)\s+(?:height|width|depth|clearance)\b"
    r"|\b(?:height|width|depth|clearance)\s+(?:of|for)\s+(?:a\s+|an\s+|the\s+)?(?:ramp|shower|seat|stairs?|doorway|hallway|bathroom|toilet)\b"
    r"|\b(?:is|are|was|were|would|could|should)\b[^.!?\n]{0,80}\b(?:safe|safer|safest|dangerous|hazardous|risky)\b"
    r"|\bhow\s+(?:safe|dangerous|risky)\b"
    r"|\b(?:determine|determining|assess|assessing|evaluate|evaluating)\b[^.!?\n]{0,60}\b(?:safe|safety|dangerous|risk|risks)\b"
    r"|\b(?:safe|safer|safest)\s+(?:option|options|choice|choices|design|layout|way|alternative|alternatives)\b"
)
HUMAN_TRIGGER_PATTERN = re.compile(
    r"(?i)\b(?:"
    r"quote|quotation|how\s+much\s+(?:does|would|will|do you charge|is it going to cost|is the price|is the cost)|"
    r"actual\s+(?:price|cost)|current\s+(?:price|cost)|price\s+(?:amount|out the door)|estimated\s+cost|free\s+(?:estimate|estimates)|"
    r"founding|founded|founder|company\s+history|established|start\s+date|opening\s+date|"
    r"when\s+did\s+(?:the\s+)?company\s+(?:start|begin|open)|who\s+(?:owns|founded)|"
    r"insurance\s+(?:guarantee|quote|coverage|certificate)|warranty|warranties|guarantee|bonded|insured|"
    r"availability|available\s+(?:now|today|next week|this month)|"
    r"when\s+(?:can|could)\s+(?:you|the team)\s+start|"
    r"schedule\s+(?:a|an|my|our|the)\s+(?:site|visit|consultation|call|appointment)|book|"
    r"send\s+(?:an?\s+)?email|arrange\s+a\s+(?:meeting|call|visit)|set\s+up\s+a\s+(?:call|meeting|visit)|"
    r"call\s+me|contact\s+me|I need more help|can I talk to someone|can I speak to"
    r")\b"
)
STRUCTURAL_ENGINEERING_HUMAN_PATTERN = re.compile(
    r"(?i)\b(?:structural\s+(?:loads?|calculations?|engineering|analysis)|"
    r"load[ -]bearing|foundation\s+(?:calculations?|engineering|design)|"
    r"wind\s+(?:load|engineering|calc)|seismic|shear\s+walls?|"
    r"engineering\s+(?:calculations?|analysis|design)|specific\s+(?:engineering|structural)\s+question|"
    r"(?:beam|joist|header|column|footing|slab)\s+(?:sizing|size|span|calculation|load))\b"
)
SAFE_GREETING_PATTERN = re.compile(r"(?i)^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|thanks|thank\s+you)[\s!.]*$")

def redact(text, limit=1500):
    text = unicodedata.normalize("NFKC", str(text))
    text = CONTROL.sub(" ", text)
    text = TOKEN.sub("[credential removed]", text)
    text = URL.sub("[URL removed]", text)
    text = EMAIL.sub("[email removed]", text)

    def hide_ip(match):
        value = match.group().strip("[]").split("%", 1)[0]
        # Do not redact ordinary words/numbers; require actual IPv4/IPv6 parsing.
        try:
            ipaddress.ip_address(value)
            return "[IP removed]"
        except ValueError:
            return match.group()
    text = IP_CANDIDATE.sub(hide_ip, text)
    text = PHONE.sub("[phone removed]", text)
    return " ".join(text.split())[:limit]


def normalize(text):
    return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", text).casefold()).split())


def classify_question(raw):
    if not isinstance(raw, str):
        return 'blocked', 'invalid type'
    t = unicodedata.normalize('NFKC', raw)
    n = ' ' + normalize(t) + ' '
    if not n.strip():
        return 'blocked', 'empty'
    if SLUR_PATTERN.search(n) or ' fucking shit ' in n:
        return 'blocked', 'explicit slur or abuse'
    if EXPLICIT_VIOLENCE_PROTECTED_PATTERN.search(t):
        return 'blocked', 'explicit violence toward protected people'
    if CREDENTIAL_PATTERN.search(t) or INJECTION_PATTERN.search(t):
        return 'blocked', 'credential or injection'
    if PRIVATE_DATA_PATTERN.search(t) or PRIVATE_URL_PATTERN.search(t):
        return 'blocked', 'private data or action'
    sex_req = any(p in n for p in (' send nudes ',' show nudes ',' sex chat ',' hook up ',' write porn ',' describe sex ',' sexual roleplay ',' escort service ',' tell me about sex ',' sex construction ',' explicit sexual activity ',' explicit sexual content ',' sexual activity ',' sexual content '))
    legit_sex = LEGIT_SEXUAL_CONSTRUCTION_PATTERN.search(t) or any(w in n for w in (' sex bolt ',' sex bolts ',' sexbolt ',' sexbolts ',' male plumbing ',' female plumbing ',' male fitting ',' female fitting ')) or re.search(r'\b(?:male|female)\b[^.!?]{0,40}\b(?:plumbing|fittings?)\b', t, re.IGNORECASE)
    if (NSFW_PATTERN.search(t) or sex_req or (' sex ' in n and not legit_sex)) and not (legit_sex and not NSFW_PATTERN.search(t) and not sex_req):
        return 'blocked', 'sexual content'
    slur_hit = SLUR_PATTERN.search(t) is not None
    if slur_hit:
        return 'blocked', 'hateful or discriminatory judgment'
    group = re.search(r'\b(?:blacks?|whites?|asians?|hispanics?|latinos?|latinas?|immigrants?|muslims?|christians?|jews?|women|men|disabled|elderly|gays?|lesbians?|transgender(?: people| persons?)?)\b', n, re.I)
    pg = group.group(0).lower() if group else ''
    people_cue = re.search(r'\b(?:people|persons?|workers?|employees?|customers?|clients?|residents?|tenants?|groups?|communities)\b', n, re.I)
    protected_people = bool(group and (people_cue or pg not in ('black', 'white')))
    access_ctx = bool(re.search(r'\b(?:accessibility|accessible|ada|accommodations?|disabled access|ramps?|lifts?|walk[- ]in shower|showers?|stairs?|layouts?|grab bars?|raised seats?|deep squats?|squats?|cannot do stairs|should not be climbing|better served|better off|design[- ]build|scope is defined)\b', n, re.I))
    material_ctx = bool(re.search(r'\b(?:roofs?|roofing|shingles?|tiles?|paint|coatings?|metal|membrane|raceway|dimensions?|sex bolts?|male plumbing|female plumbing|male fittings?|female fittings?)\b', n, re.I))
    black_white_material = pg in ('black', 'white') and material_ctx and not people_cue
    strong_hate = bool(re.search(r'\b(?:not be allowed|not allowed|not work|not welcome)|\b(?:are|is)\s+(?:inferior|superior|lazy|dishonest)|\bdont want\b|\bdo not want\b|\bhate\b|\bdespise\b|\bno (?:women|men|disabled|elderly|immigrants|muslims|christians|jews|gays|lesbians)\b', n, re.I))
    broad_hit = HATE_DISCRIMINATION_PATTERN.search(t)
    cmp_hit = re.search('\\b(?:\\b\\b(?:blacks?|whites?|asians?|hispanics?|latinos?|latinas?|immigrants?|muslims?|christians?|jews?|women|men|disabled|elderly|gays?|lesbians?|transgender(?: people| persons?)?)\\b(?:\\s+(?:\\b(?:people|persons?|workers?|employees?|customers?|clients?|residents?|tenants?|groups?|communities)\\b|\\b(?:blacks?|whites?|asians?|hispanics?|latinos?|latinas?|immigrants?|muslims?|christians?|jews?|women|men|disabled|elderly|gays?|lesbians?|transgender(?: people| persons?)?)\\b))?\\b\\s+(?:are|is|was|were)\\s+(?:(?:much|far|still|even|any)\\s+)?(?:worse|bad|better)\\b(?:\\s+(?:at|in|for|as)\\s+\\w+(?:\\s+\\w+){0,3}|\\s+\\w+(?:\\s+\\w+){0,2})?|(?:are|is|was|were)\\s+\\b\\b(?:blacks?|whites?|asians?|hispanics?|latinos?|latinas?|immigrants?|muslims?|christians?|jews?|women|men|disabled|elderly|gays?|lesbians?|transgender(?: people| persons?)?)\\b(?:\\s+(?:\\b(?:people|persons?|workers?|employees?|customers?|clients?|residents?|tenants?|groups?|communities)\\b|\\b(?:blacks?|whites?|asians?|hispanics?|latinos?|latinas?|immigrants?|muslims?|christians?|jews?|women|men|disabled|elderly|gays?|lesbians?|transgender(?: people| persons?)?)\\b))?\\b\\s+(?:(?:often|usually|generally|typically|always|never|rarely|sometimes)\\s+)?(?:worse|bad|better)\\b(?:\\s+(?:off|served)\\b(?:\\s+by\\s+\\w+(?:\\s+\\w+){0,3})?|\\s+(?:at|in|for|as)\\s+\\w+(?:\\s+\\w+){0,3}|\\s+\\w+(?:\\s+\\w+){0,2})?)\\b', n, re.I)
    physical_service = bool(access_ctx and pg in ('disabled', 'elderly') and re.search(r'\b(?:better served|better off|cannot do|should not be climbing|deep squats?|raised seats?|walk[- ]in shower|grab bars?)\b', n, re.I))
    broad_service = False
    if broad_hit:
        context_start = max(t.rfind(mark, 0, broad_hit.start()) for mark in '.!?\n') + 1
        context_end = len(t)
        for mark in '.!?\n':
            pos = t.find(mark, broad_hit.end())
            if pos != -1:
                context_end = min(context_end, pos)
        broad_context = ' ' + normalize(t[context_start:context_end]) + ' '
        broad_service = bool(
            re.search(
                r'\bbetter\s+(?:served|off)\s+(?:with|by|using)\s+(?:a\s+|an\s+|the\s+)?'
                r'(?:ramps?|lifts?|grab\s+bars?|walk\s+in\s+showers?|roll\s+in\s+showers?|barrier\s+free\s+showers?|shower\s+seats?|bath\s+seats?|raised\s+seats?)\b'
                r'|\b(?:cannot|can\s+not)\s+do\s+stairs\b'
                r'|\b(?:should\s+not|shouldn\s+t)\s+be\s+climbing\s+stairs\b',
                broad_context,
                re.I,
            )
            and not re.search(
                r'\b(?:inferior|superior|stupid|lazy|evil|disgusting|unfit|violent|terrorists?|dishonest|bad|worse|smarter|hate|despise)\b'
                r'|\bnot\s+(?:be\s+)?(?:capable|qualified|welcome|allowed)\b'
                r'|\b(?:do\s+not|don\s+t)\s+belong\b|\bshould\s+not\s+(?:be\s+allowed|belong)\b'
                r'|\bshouldn\s+t\s+(?:be\s+allowed|belong)\b|\b(?:cannot|can\s+not)\s+work\b',
                broad_context,
                re.I,
            )
        )
    if strong_hate and protected_people:
        return 'blocked', 'hateful or discriminatory judgment'
    if protected_people and cmp_hit and not black_white_material and not (physical_service and re.search(r'\bbetter\s+(?:served|off)\b', cmp_hit.group(0), re.I) and not re.search(r'\b(?:bad|worse|smarter|inferior|superior|lazy|dishonest)\b', cmp_hit.group(0), re.I) and not re.search(r'\bbetter\s+(?:at|than)\b', n, re.I)):
        return 'blocked', 'hateful or discriminatory judgment'
    if broad_hit and protected_people and not broad_service and not black_white_material:
        return 'blocked', 'hateful or discriminatory judgment'
    religion_opinion = re.search(r'\b(?:think|thinking|opinion|opinions|feel|feels|view|views)\b[^.!?]*\b(?:organized\s+religion|religion)\b', n, re.IGNORECASE)
    if RELIGIOUS_POLITICAL_DEBATE_PATTERN.search(t) or religion_opinion or any(p in n for p in (' what religion is true ',' which religion is true ',' religion is true ',' is god real ',' political opinion ')):
        return 'blocked', 'religious or political debate'
    if OFFTOPIC_PATTERN.search(t):
        return 'blocked', 'off-topic'
    neutral_context = legit_sex or any(w in n for w in (' homeowner ',' service ',' ada ',' disabled access ',' accessible fitting ',' accessible fittings ',' threaded fitting ',' threaded fittings '))
    construction = CONSTRUCTION_CONTEXT_PATTERN.search(t) or neutral_context or re.search(r'\b(?:miami|square\s+feet?|square\s+footage|per\s+square\s+foot)\b', t, re.IGNORECASE)
    profanity = any(' ' + w + ' ' in n for w in ('damn','hell','crap','shit','fuck','fucking','bitch','asshole','bastard','pissed','sucks','wtf'))
    if profanity and not construction:
        return 'blocked', 'pure abuse'
    if SAFE_GREETING_PATTERN.search(t):
        return 'safe', 'greeting'
    structural = STRUCTURAL_ENGINEERING_HUMAN_PATTERN.search(t) or (any(w in n for w in (' beam ',' beams ',' foundation ',' foundations ',' footing ',' footings ',' column ',' columns ')) and any(w in n for w in (' size ',' sizing ',' dimension ',' dimensions ',' span ',' load ',' loads ',' diy ',' step ',' steps ',' design ',' calculate ',' thickness ',' depth ')))
    if structural:
        return 'human', 'engineering sizing or calculations'
    if ACCESSIBILITY_HUMAN_PATTERN.search(t) or SAFETY_DIMENSION_HUMAN_PATTERN.search(t):
        return 'human', 'accessibility, safety, dimensions, or project-specific advice'
    actual_scope = re.search(r'\bactual\s*quote\b|\bfirm\s*(?:price|quote|cost)\b|\bguarantee(?:d|s)?\b|\bstart\s*date\b|\b(?:call|email|contact)\s+me\b|\bbook\s+(?:an?\s+)?appointment\b|\b(?:send|provide|give|request)\s+me\s+(?:(?:a|an|the|with|your|my|our|their)\s+)*quote\b', n, re.IGNORECASE)
    general_scope = re.search(r'\b(?:what|which)\s+factors?\b[^.!?]*\b(?:pricing|price|cost|estimate|estimates|materials?|roofing)\b|\bestimate\s+process\b|\b(?:pricing|price|cost)s?\s+factors?\b', n, re.IGNORECASE)
    company_scope = re.search(r'\b(?:company|business|you|your)\b[^.!?]*\b(?:use|uses|used|follow|follows|prefer|prefers|install|installs|recommend|recommends)\b[^.!?]*\b(?:materials?|roofing|shingles?)\b|\b(?:materials?|roofing\s+practices?)\b[^.!?]*\b(?:company|business|you|your)\b', n, re.IGNORECASE)
    if company_scope or actual_scope or ((HUMAN_TRIGGER_PATTERN.search(t) or UNSUPPORTED.search(t)) and not general_scope):
        return 'human', 'company specific, pricing, schedule, warranty, insurance, or action request'
    if SAFE_PROCESS_PATTERN.search(t) or general_scope:
        return 'safe', 'general process guidance'
    if construction:
        return 'safe', 'construction or company context'
    return 'blocked', 'arbitrary off-topic'


def sanitize_question(text):
    t = unicodedata.normalize('NFKC', str(text or ''))
    n = ' ' + normalize(t) + ' '
    for w in ('damn','hell','crap','shit','fuck','fucking','bitch','asshole','bastard','pissed','sucks','wtf'):
        t = re.sub(r'(?i)\b' + re.escape(w) + r'\b', ' ', t)
    return redact(t)


def validate_question(body):
    if not isinstance(body, dict) or set(body) != {'question'}:
        raise ValueError('Only the question field is accepted')
    q = body['question']
    if not isinstance(q, str) or not 2 <= len(q.strip()) <= 1500:
        raise ValueError('question must contain 2 to 1500 characters')
    if any(unicodedata.category(c) == 'Cs' for c in q):
        raise ValueError('Invalid Unicode')
    if any(unicodedata.category(c) == 'Cf' for c in q):
        raise ValueError('Invalid control formatting')
    q = sanitize_question(q.strip())
    if len(normalize(q)) < 2:
        raise ValueError('question must contain readable text')
    return q

def client_ip(peer, headers, trust_proxy=False):
    # Railway must overwrite/sanitize X-Forwarded-For and prevent direct origin access.
    # Only the rightmost hop is considered, never an attacker-supplied first hop.
    candidate = peer
    if trust_proxy:
        candidate = headers.get("X-Forwarded-For", "").split(",")[-1].strip() or peer
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return str(ipaddress.ip_address(peer))


def csv_safe(value):
    text = str(value)
    dangerous = text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@"))
    return "'" + text if dangerous else text
