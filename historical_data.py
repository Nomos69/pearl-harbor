"""Concise, sourced historical context shown before country selection.

The game rosters are deliberately smaller than the real opposing forces. Gameplay
lengths are not historical scale data.
"""

from __future__ import annotations


OPERATION_FACTS = (
    ("DATE", "Sunday, 7 December 1941"),
    ("LOCATION", "Pearl Harbor and military installations across Oahu, Hawaii Territory"),
    ("FIRST WAVE", "07:55 Hawaii Standard Time"),
    ("JAPANESE PLAN", "Hawaii Operation"),
    ("STRIKE FORCE", "Dai-ichi Kido Butai (First Mobile Striking Force)"),
    ("ATTACK", "353 carrier aircraft in two waves; five midget submarines also deployed"),
)

BACKGROUND = (
    "Japan sought to disable the U.S. Pacific Fleet while opening campaigns in "
    "Southeast Asia. Six Japanese fleet carriers approached in secrecy and launched "
    "two air waves against ships and airfields on Oahu. U.S. aircraft carriers were "
    "not in Pearl Harbor. The attack brought the United States into World War II."
)

TEAM_DOSSIERS = {
    "US": {
        "government": (
            "President: Franklin D. Roosevelt",
            "Pacific Fleet: Adm. Husband E. Kimmel",
            "Hawaiian Department: Lt. Gen. Walter C. Short",
        ),
        "fleet_note": "Five game vessels selected from the much larger U.S. force present:",
        "ships": (
            ("USS Arizona (BB-39)", "Battleship; destroyed, with 1,177 killed aboard"),
            ("USS Oklahoma (BB-37)", "Battleship; capsized, with 429 killed"),
            ("USS Helena (CL-50)", "Light cruiser; torpedo-damaged and later repaired"),
            ("USS Shaw (DD-373)", "Destroyer; heavily bombed, later repaired"),
            ("USS Nevada (BB-36)", "Battleship; got underway, beached, and later repaired"),
        ),
        "historical_note": "The U.S. Pacific Fleet's aircraft carriers were away from Pearl Harbor.",
    },
    "Japan": {
        "government": (
            "Head of state: Emperor Hirohito",
            "Prime Minister: Hideki Tojo",
            "Combined Fleet: Adm. Isoroku Yamamoto",
            "Strike Force: Vice Adm. Chuichi Nagumo",
        ),
        "fleet_note": "Five game vessels selected from the larger Japanese attack force:",
        "ships": (
            ("Akagi", "Fleet carrier; Nagumo's flagship"),
            ("Kaga", "Fleet carrier; Carrier Division 1"),
            ("Shokaku", "Fleet carrier; Carrier Division 5"),
            ("Soryu", "Fleet carrier; Carrier Division 2"),
            ("I-22", "Fleet submarine; launched a midget submarine for the attack"),
        ),
        "historical_note": "The six-carrier force also included Hiryu and Zuikaku.",
    },
}

HISTORICAL_NOTE = (
    "Historically inspired, not a literal simulation. Fleets, grid lengths, and "
    "symmetric turns are balanced for two-player gameplay."
)

SOURCE_LABEL = (
    "Verified with U.S. Naval History & Heritage Command, U.S. National Park "
    "Service, FDR Presidential Library, and the Prime Minister's Office of Japan."
)

# Short quotations verified against the National Archives, U.S. Naval History and
# Heritage Command, and the UK Parliament's historic Hansard collection.
WAR_QUOTES = (
    (
        "The American people in their righteous might will win through to absolute victory.",
        "President Franklin D. Roosevelt",
        "Address to Congress, 8 December 1941",
    ),
    (
        "The eyes of the world are upon you.",
        "Gen. Dwight D. Eisenhower",
        "D-Day Order of the Day, 6 June 1944",
    ),
    (
        "Uncommon valor was a common virtue.",
        "Fleet Adm. Chester W. Nimitz",
        "Iwo Jima communiqué, 1945",
    ),
    (
        "I have not yet begun to fight!",
        "Capt. John Paul Jones",
        "Attributed at the Battle of Flamborough Head, 1779",
    ),
    (
        "In war, there is no substitute for victory.",
        "Gen. Douglas MacArthur",
        "Address to Congress, 1951",
    ),
    (
        "Never in the field of human conflict was so much owed by so many to so few.",
        "Prime Minister Winston Churchill",
        "House of Commons, 20 August 1940",
    ),
)
