"""
Crew Name Pools — Diverse first and last names for crew generation.

200 first names and 200 surnames drawn from diverse cultural backgrounds.
Names are randomly paired at game start with no duplicates within a roster.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# First names (200) — diverse cultural backgrounds, mixed gender
# ---------------------------------------------------------------------------

FIRST_NAMES: list[str] = [
    # English / Western
    "Sarah", "James", "Emily", "Marcus", "Olivia", "Daniel", "Chloe", "Nathan",
    "Hannah", "Ryan", "Grace", "Ethan", "Lily", "Owen", "Sophie", "Liam",
    # Spanish / Latin American
    "Carlos", "Isabella", "Diego", "Valentina", "Alejandro", "Camila", "Mateo",
    "Lucia", "Santiago", "Sofia", "Rafael", "Mariana", "Gabriel", "Elena",
    "Fernando", "Ximena", "Andres", "Catalina", "Joaquin", "Paloma",
    # Chinese
    "Mei", "Wei", "Jing", "Chen", "Lan", "Hao", "Xiu", "Jun", "Yue", "Zhi",
    "Lian", "Feng", "Shan", "Bao", "Ning", "Tao", "Rui", "Xia", "Qian", "Ming",
    # Indian / South Asian
    "Priya", "Arjun", "Ananya", "Rohan", "Kavya", "Vikram", "Aisha", "Sanjay",
    "Divya", "Kiran", "Nandini", "Ravi", "Sunita", "Arun", "Deepa", "Harsh",
    "Meera", "Nikhil", "Pooja", "Rahul",
    # Japanese
    "Kenji", "Yuki", "Haruki", "Sakura", "Takeshi", "Aiko", "Ren", "Hana",
    "Akira", "Mio", "Kaito", "Natsumi", "Shinji", "Emi", "Daichi", "Sora",
    # Korean
    "Jiwoo", "Minjun", "Soojin", "Hyun", "Eunji", "Taehyung", "Yuna", "Seojun",
    "Minji", "Jihoon",
    # Arabic / Middle Eastern
    "Tariq", "Layla", "Omar", "Fatima", "Khalid", "Nadia", "Hassan", "Amina",
    "Yusuf", "Samira", "Ibrahim", "Zara", "Rashid", "Leila", "Karim", "Dina",
    # African (various regions)
    "Amara", "Oluwaseun", "Chioma", "Kwame", "Nia", "Tendai", "Zola", "Kofi",
    "Adaeze", "Jelani", "Thandiwe", "Emeka", "Ayo", "Makena", "Chidi", "Ife",
    "Sekou", "Amani", "Binta", "Jabari",
    # Russian / Eastern European
    "Dmitri", "Aleksandra", "Nikolai", "Katarina", "Pavel", "Yelena", "Oleg",
    "Natasha", "Ivan", "Svetlana", "Boris", "Irina", "Sergei", "Tatiana",
    "Mikhail", "Anastasia",
    # Pacific Islander / Polynesian
    "Aroha", "Tane", "Moana", "Manu", "Leilani", "Sione", "Ngaire", "Kahu",
    "Marama", "Wiremu",
    # Indigenous Australian
    "Jarrah", "Kirra", "Bindi", "Marali", "Allira", "Tjiirdm", "Yindi", "Jedda",
    # Nordic / Scandinavian
    "Astrid", "Erik", "Freya", "Bjorn", "Sigrid", "Leif", "Ingrid", "Sven",
    # Southeast Asian
    "Linh", "Anh", "Thida", "Aroon", "Malaya", "Rizal", "Dewi", "Budi",
    # Other
    "Ezra", "Quinn", "Rowan", "Sage", "Phoenix", "River", "Skye",
    "Morgan", "Avery", "Jordan", "Casey", "Robin",
]

assert len(FIRST_NAMES) == 200, f"Expected 200 first names, got {len(FIRST_NAMES)}"

# ---------------------------------------------------------------------------
# Surnames (200) — diverse cultural backgrounds
# ---------------------------------------------------------------------------

SURNAMES: list[str] = [
    # English / Western
    "Williams", "Johnson", "Smith", "Brown", "Davis", "Wilson", "Taylor",
    "Anderson", "Thomas", "Campbell", "Mitchell", "Roberts", "Clarke", "Stewart",
    "Hughes", "Walker", "Scott", "Baker", "Green", "Hall",
    # Spanish / Latin American
    "Martinez", "Garcia", "Rodriguez", "Lopez", "Hernandez", "Gonzalez",
    "Ramirez", "Torres", "Flores", "Morales", "Castillo", "Reyes", "Ortiz",
    "Delgado", "Vargas", "Mendoza", "Guerrero", "Rios", "Padilla", "Soto",
    # Chinese
    "Chen", "Wang", "Zhang", "Li", "Liu", "Yang", "Zhao", "Huang", "Zhou", "Wu",
    "Sun", "Ma", "Xu", "Lin", "Guo",
    # Indian / South Asian
    "Krishnamurthy", "Sharma", "Patel", "Singh", "Gupta", "Bhat", "Mehta",
    "Reddy", "Nair", "Joshi", "Rao", "Chatterjee", "Das", "Banerjee", "Desai",
    # Japanese
    "Tanaka", "Nakamura", "Yamamoto", "Suzuki", "Watanabe", "Sato", "Takahashi",
    "Ito", "Kobayashi", "Kato", "Yoshida", "Yamada", "Mori", "Hayashi", "Shimizu",
    # Korean
    "Kim", "Park", "Choi", "Jung", "Kang", "Cho", "Yoon", "Lim", "Han", "Shin",
    # Arabic / Middle Eastern
    "Al-Rashid", "Hassan", "Ibrahim", "Khalil", "Mansour", "Nasser", "Saleh",
    "Abbas", "Farid", "Habib", "Moussa", "Saeed", "Taha", "Yassin", "Hariri",
    # African (various regions)
    "Okafor", "Adeyemi", "Mensah", "Diallo", "Osei", "Mwangi", "Ngozi",
    "Traore", "Conteh", "Afolabi", "Chimelu", "Okoro", "Amadi", "Kenyatta",
    "Mbeki", "Ndlovu", "Abara", "Achebe", "Nwosu", "Eze",
    # Russian / Eastern European
    "Volkov", "Petrov", "Ivanov", "Kuznetsov", "Popov", "Sokolov", "Lebedev",
    "Kowalski", "Novak", "Dvorak", "Horvat", "Petrovic", "Kovacs", "Szabo",
    "Polak",
    # Pacific Islander / Polynesian
    "Tui", "Matai", "Aroha", "Taonga", "Pene", "Latu", "Manu", "Taufa",
    "Vunipola", "Fa'alogo",
    # Indigenous Australian
    "Yunupingu", "Mundine", "Langton", "Mabo", "Pearson",
    # Nordic / Scandinavian
    "Johansson", "Larsson", "Eriksson", "Berg", "Lund", "Strand", "Dahl",
    "Holmberg", "Lindqvist", "Nygaard",
    # Southeast Asian
    "Nguyen", "Tran", "Pham", "Hoang", "Le", "Suryadi", "Wibowo", "Santos",
    "Cruz", "Reyes",
    # Other / Compound
    "O'Brien", "MacDonald", "Van der Berg", "De Silva", "Al-Farsi",
    "St. Claire", "El-Amin", "Fitzpatrick", "Beaumont", "Montague",
    "Ashworth", "Blackwell", "Fairfax", "Hartwell", "Kingsley",
    "Lancaster", "Prescott", "Sterling", "Whitmore", "Carmichael",
]

assert len(SURNAMES) == 200, f"Expected 200 surnames, got {len(SURNAMES)}"
