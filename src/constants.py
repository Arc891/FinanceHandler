from enum import Enum

# ─────────────────────────────────────────────────────────────────────────────
# - ENUMS FOR EXPENSE AND INCOME CATEGORIES
#    Each category has a label and a regex pattern for matching.
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseCategory(str, Enum):
    """
    Each member's `value` is the exact label (for Google Sheets, etc.),
    and `pattern` is the minimal regex that should match for manual-categorization.
    """

    pattern: str

    def __new__(cls, label: str, pattern: str):
        # Create the str‐value itself:
        obj = str.__new__(cls, label)
        obj._value_ = label
        # Attach a `pattern` attribute to each member:
        obj.pattern = pattern
        return obj

    ABONNEMENTEN            = ("Abonnementen",            r"ab")
    ANDER                   = ("Ander",                   r"an")
    AUTO_VERVOER_OV         = ("Auto / vervoer / OV",     r"au")
    BOODSCHAPPEN            = ("Boodschappen",            r"bo")
    CADEAUTJES              = ("Cadeautjes",              r"ca")
    DATES_UITJES            = ("Dates/uitjes",            r"da|ui")
    GAS_WATER_ELECTRA       = ("Gas/water/electra",       r"ga")
    GOEIE_DOELEN            = ("Goeie doelen",            r"go")
    HUISHOUDEN              = ("Huishouden",              r"hu")
    NAAR_SPAARPOTJES        = ("Naar spaarpotjes",        r"ns")
    PERSOONLIJK_VRIJ_GELD   = ("Persoonlijk vrij geld",   r"pvg")
    PERSOONLIJKE_VERZORGING = ("Persoonlijke verzorging", r"pvz")
    REKENINGEN              = ("Rekeningen",              r"re")
    SNACKEN                 = ("Snacken",                 r"sn")
    UIT_SPAARPOTJE          = ("Uit spaarpotje",          r"us")
    NOG_IN_TEDELEN          = ("! Nog in te delen !",     r"nog|!")
    VERZEKERINGEN           = ("Verzekeringen",           r"ve")
    ZORGVERZEKERING         = ("Zorgverzekering",         r"zo")
    DUMMY_CACHED            = ("🔄 CACHED",                r"dummy|cache")

    DEFAULT                 = NOG_IN_TEDELEN


class IncomeCategory(str, Enum):
    """
    Each member's `value` is the exact income label,
    and `pattern` is the minimal regex for matching.
    """

    pattern: str

    def __new__(cls, label: str, pattern: str):
        obj = str.__new__(cls, label)
        obj._value_ = label
        obj.pattern = pattern
        return obj

    SALARIS               = ("Salaris",               r"sa")
    SPAARREKENING         = ("Spaarrekening",         r"sp")
    BONUS                 = ("Bonus",                 r"bo")
    OVERHEID              = ("Overheid",              r"ov")
    GIFT                  = ("Gift",                  r"gi")
    PERSONLIJKE_REKENING  = ("Persoonlijke rekening", r"pe")
    GEMEENTE              = ("Gemeente",              r"ge")
    DUMMY_CACHED            = ("🔄 CACHED",                r"dummy|cache")

    DEFAULT               = PERSONLIJKE_REKENING

# ─────────────────────────────────────────────────────────────────────────────
# - AUTO‐CATEGORIZATION RULES (SEPARATE FOR EXPENSE & INCOME)
#    Keys are regex patterns; values are (description_template, category).
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIZATION_RULES_EXPENSE = {
    r"gebruik betaalrekening":         ("ASN Gebruikskosten", ExpenseCategory.ABONNEMENTEN),
    r"maandelijkse bijdrage familie":  ("{c} uitjes",   ExpenseCategory.ABONNEMENTEN),
    r"Apple opslag en app pomodoro":   ("{c} Janneke",  ExpenseCategory.ABONNEMENTEN),
    r"Simpel|Vodafone":                ("{c} telefoon", ExpenseCategory.ABONNEMENTEN),
    r"consumentenbond|ANWB":           ("{c}", ExpenseCategory.ABONNEMENTEN),
    r"lensplaza":                      ("Lenzen Janneke",  ExpenseCategory.ABONNEMENTEN),
    r"ODIDO":                          ("{c} Internet/TV", ExpenseCategory.ABONNEMENTEN),
    r"Kuario":                         ("Printen Bieb Driebergen", ExpenseCategory.ANDER),
    r"TinQ|Tango":                     ("{c} tanken", ExpenseCategory.AUTO_VERVOER_OV),
    r"Greenwheels":                    ("{c} auto",   ExpenseCategory.AUTO_VERVOER_OV),
    r"ovpay|NS GROEP":                 ("{c} OV kosten", ExpenseCategory.AUTO_VERVOER_OV),
    r"JUMBO|PICNIC|LIDL|AH to go|ALBERT HEIJN|VOMAR|PLUS|Fruitcompany": ("{c} inkopen", ExpenseCategory.BOODSCHAPPEN),
    r"snack company|snackbar traay":   ("{c} eten", ExpenseCategory.DATES_UITJES),
    r"vitens":                         ("{c} water", ExpenseCategory.GAS_WATER_ELECTRA),
    r"ENGIE":                          ("{c} energie", ExpenseCategory.GAS_WATER_ELECTRA),
    r"sponsorbijdrage":                ("Compassion Midina", ExpenseCategory.GOEIE_DOELEN),
    r"(?i)(?=.*\b(?:donatie|gift|bijdrage)\b).*?\W ([A-Za-z0-9 &\-\.]+)$": ("Donatie/bijdrage aan {c}", ExpenseCategory.GOEIE_DOELEN),
    r"Kantoor der Kerkelijke Goederen": ("Huur {c}", ExpenseCategory.HUISHOUDEN),
    r"maandelijks spaargeld - (\w+)":  ("Sparen - {c}", ExpenseCategory.NAAR_SPAARPOTJES),
    r"vrij geld (\w+)":                ("Vrij geld {c}", ExpenseCategory.PERSOONLIJK_VRIJ_GELD),
    r"Bolhaar":                        ("{c} zorgkosten", ExpenseCategory.REKENINGEN),
    r"Huiskamer":                      ("{c} snackje", ExpenseCategory.SNACKEN),
    r"(\w+) PROMOVENDUM":              ("Promovendum {c}", ExpenseCategory.VERZEKERINGEN),
    r"zorgkostennota":                 ("Zorgkosten terugbetaling", ExpenseCategory.ZORGVERZEKERING),
    r"zilveren kruis|de christelijke zorg": ("{c} zorgverzekering",      ExpenseCategory.ZORGVERZEKERING),
}

CATEGORIZATION_RULES_INCOME = {
    r"DUO":                  ("{c} uitkering", IncomeCategory.OVERHEID),
    r"SALARIS":              ("{c} Ezra",      IncomeCategory.SALARIS),
    r"BONUS":                ("{c} bonus",     IncomeCategory.BONUS),
    r"GEMEENTE":             ("{c} uitkering", IncomeCategory.GEMEENTE),
}
