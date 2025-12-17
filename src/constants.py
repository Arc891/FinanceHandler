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
    DUMMY_CACHED            = ("CACHED",               r"dummy|cache")

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
    DUMMY_CACHED          = ("CACHED",                r"dummy|cache")

    DEFAULT               = PERSONLIJKE_REKENING

# ─────────────────────────────────────────────────────────────────────────────
# - AUTO‐CATEGORIZATION RULES (SEPARATE FOR EXPENSE & INCOME)
#    Keys are regex patterns; values are (description_template, category).
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIZATION_RULES_EXPENSE = {
    # Abonnementen
    r"gebruik betaalrekening":         ("ASN Gebruikskosten", ExpenseCategory.ABONNEMENTEN),
    r"maandelijkse bijdrage familie":  ("{c} uitjes",   ExpenseCategory.ABONNEMENTEN),
    r"Apple opslag en app pomodoro":   ("{c} Janneke",  ExpenseCategory.ABONNEMENTEN),
    r"Simpel|Vodafone":                ("{c} telefoon", ExpenseCategory.ABONNEMENTEN),
    r"consumentenbond|ANWB":           ("{c}", ExpenseCategory.ABONNEMENTEN),
    r"lensplaza":                      ("Lenzen Janneke",  ExpenseCategory.ABONNEMENTEN),
    r"ODIDO":                          ("{c} Internet/TV", ExpenseCategory.ABONNEMENTEN),

    # Ander
    r"Kuario":                         ("Printen Bieb Driebergen", ExpenseCategory.ANDER),

    # Auto / vervoer / OV
    r"TinQ|Tango":                     ("{c} tanken", ExpenseCategory.AUTO_VERVOER_OV),
    r"Greenwheels":                    ("{c} auto",   ExpenseCategory.AUTO_VERVOER_OV),
    r"ovpay|NS GROEP":                 ("{c} OV kosten", ExpenseCategory.AUTO_VERVOER_OV),

    # Boodschappen
    r"JUMBO|PICNIC|LIDL|AH to go|ALBERT HEIJN|VOMAR|PLUS|Fruitcompany|Odin|Lakerveld": ("{c} inkopen", ExpenseCategory.BOODSCHAPPEN),
    r"Ararat":                         ("{c} groente/fruit", ExpenseCategory.BOODSCHAPPEN),
    r"Vigola":                         ("{c} delicatessen", ExpenseCategory.BOODSCHAPPEN),

    # Dates/uitjes
    r"snack company|snackbar traay":   ("{c} eten", ExpenseCategory.DATES_UITJES),

    # Gas/water/electra
    r"vitens":                         ("{c} water", ExpenseCategory.GAS_WATER_ELECTRA),
    r"ENGIE":                          ("{c} energie", ExpenseCategory.GAS_WATER_ELECTRA),

    # Goeie doelen - specific charities (more reliable than generic pattern)
    r"sponsorbijdrage":                ("Compassion Midina", ExpenseCategory.GOEIE_DOELEN),
    r"Kinderen Kankervrij|KiKa":       ("Donatie {c}", ExpenseCategory.GOEIE_DOELEN),
    r"Jesus in the Streets":           ("Donatie {c}", ExpenseCategory.GOEIE_DOELEN),
    r"Utrechts Landschap":             ("Donatie {c}", ExpenseCategory.GOEIE_DOELEN),
    r"NEDERLANDS BIJBELGENOOTSCHAP":   ("Donatie {c}", ExpenseCategory.GOEIE_DOELEN),
    r"Zij Lacht":                      ("Donatie {c}", ExpenseCategory.GOEIE_DOELEN),
    r"World Vision|Wereldvisie":       ("Donatie {c}", ExpenseCategory.GOEIE_DOELEN),
    r"Rode Kruis":                     ("Donatie {c}", ExpenseCategory.GOEIE_DOELEN),
    r"Natuurmonumenten":               ("Donatie {c}", ExpenseCategory.GOEIE_DOELEN),
    r"GoFundMe":                       ("Donatie via {c}", ExpenseCategory.GOEIE_DOELEN),

    # Huishouden
    r"Kantoor der Kerkelijke Goederen": ("Huur {c}", ExpenseCategory.HUISHOUDEN),

    # Naar spaarpotjes
    r"maandelijks spaargeld\s*[-]?\s*(\w+)": ("Sparen - {c}", ExpenseCategory.NAAR_SPAARPOTJES),

    # Persoonlijk vrij geld
    r"vrij geld (\w+)":                ("Vrij geld {c}", ExpenseCategory.PERSOONLIJK_VRIJ_GELD),

    # Rekeningen
    r"Bolhaar":                        ("{c} zorgkosten", ExpenseCategory.REKENINGEN),
    r"zorgkostennota":                 ("Zorgkosten terugbetaling", ExpenseCategory.REKENINGEN),

    # Snacken
    r"Huiskamer":                      ("{c} snackje", ExpenseCategory.SNACKEN),

    # Verzekeringen
    r"(\w+) PROMOVENDUM":              ("Promovendum {c}", ExpenseCategory.VERZEKERINGEN),

    # Zorgverzekering
    r"zilveren kruis|de christelijke zorg": ("{c} zorgverzekering", ExpenseCategory.ZORGVERZEKERING),
}

CATEGORIZATION_RULES_INCOME = {
    r"DUO":                  ("{c} uitkering", IncomeCategory.OVERHEID),
    r"SALARIS":              ("{c} Ezra",      IncomeCategory.SALARIS),
    r"BONUS":                ("{c} bonus",     IncomeCategory.BONUS),
    r"GEMEENTE":             ("{c} uitkering", IncomeCategory.GEMEENTE),
    r"zorgkostennota":       ("Zorgkosten terugbetaling", IncomeCategory.PERSONLIJKE_REKENING),
}
