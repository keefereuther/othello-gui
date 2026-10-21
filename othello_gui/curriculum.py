"""The training curriculum, following Brian Rose's "Othello: A Minute to Learn...
A Lifetime to Master" (2005).

Part I (units 1-7) is a guided path: each unit unlocks when the previous one is
passed. Part II (units 8-14) opens once Part I is done and can be taken in any
order, as the book intends. Lesson text is a summary in our own words; the
`pages` field points at the book for depth.

Each unit has

    drill       which positions to practise on and how
                kinds:   {"move": w, "judge": w, "squares": w} sampling weights
                empties: (lo, hi) empty squares in the drill position
                filter:  name of a position filter in training.FILTERS (optional)
                player:  only use games by this player (optional)
                level:   Edax level used to grade
    scrimmage   a full game against Edax
                level, variety: Edax strength (the level is nudged by results)
                threshold: discs lost that count as a mistake
                watch: what the coach pauses for (concept tags, concepts.UNIT_CONCEPTS)
                opening_plies: start from a real tournament opening (optional)
"""

from __future__ import annotations

from typing import Any

from .concepts import UNIT_CONCEPTS

UNITS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------ Part I
    {
        "id": "rules", "part": 1, "chapter": "1", "pages": "1–4",
        "title": "The board and its language",
        "lesson": [
            "Columns are a to h from left to right and rows are 1 to 8 from top to bottom, so a1 is the "
            "top-left corner and h8 the bottom-right. Black moves first. A move must flip at least one "
            "disc: you place a disc so that a straight line of the opponent's discs (along a row, column "
            "or diagonal) is sandwiched between it and one of your own discs, and every sandwiched line "
            "flips. If you have no legal move you pass; when neither side can move the game ends.",
            "Strategy is talked about in the names of the edge squares, so learn them now. The corners "
            "are a1, h1, a8 and h8. The X-squares sit diagonally next to a corner (b2, g2, b7, g7); the "
            "X marks danger. The C-squares are on the edge right next to a corner (b1, a2, g1, h2 …). "
            "Next come the A-squares (c1, a3 …) and in the middle of each edge the two B-squares "
            "(d1, e1, a4, a5 …).",
            "Almost every principle in this course is stated in these terms: \"avoid X-squares early\", "
            "\"a C-square is safe when the edge is yours\", \"leave the pair alone\". Seeing the board "
            "in these categories without thinking is the first piece of board feel.",
        ],
        "ideas": [
            "A legal move flips at least one disc; all sandwiched lines flip.",
            "No legal move: pass. Neither side can move: game over.",
            "Corner, X, C, A and B squares: the vocabulary of the rest of the course.",
        ],
        "look_for": ["Name the square before you play it.", "Notice how wildly the disc count swings during a game."],
        "drill": {"kinds": {"squares": 1.0}},
        "scrimmage": {"level": 1, "variety": 4, "threshold": 8,
                      "about": "Play a full game against a gentle Edax. Any finished game passes."},
    },
    {
        "id": "corners", "part": 1, "chapter": "2", "pages": "5–8",
        "title": "Corners and stable discs",
        "lesson": [
            "A disc on a corner can never be flipped, because there is no square beyond it to sandwich "
            "from. Discs that can never be flipped are called stable, and a corner lets you grow a block "
            "of stable discs along both edges and inward. The earlier you get a corner, the more time "
            "you have to build on it.",
            "The only way to hand your opponent a corner is to play next to it. X-squares are the worst "
            "offenders: an early X-square almost always loses the corner, because the opponent only "
            "needs one disc somewhere on that diagonal to reach it.",
            "C-squares depend on the rest of the edge. A C-square is dangerous when the A-square beside "
            "it is empty, because the opponent can attack along the edge. It is often perfectly safe "
            "when the edge is already yours, or when it extends stable discs from a corner you own.",
        ],
        "ideas": [
            "Corners cannot be flipped and anchor stable discs.",
            "Early X-squares give away corners.",
            "Judge a C-square by the rest of its edge.",
        ],
        "look_for": [
            "Is a corner available to me right now?",
            "Does my move put a disc next to an empty corner?",
            "After my move, can the opponent reach that corner?",
        ],
        "drill": {"kinds": {"move": 1.0}, "empties": (20, 44), "filter": "corner_choice", "level": 10},
        "scrimmage": {"level": 2, "variety": 2, "threshold": 6,
                      "about": "The coach pauses only for corner mistakes: X-squares, C-squares and moves that give a corner away."},
    },
    {
        "id": "frontier", "part": 1, "chapter": "3", "pages": "9–15",
        "title": "Frontier discs, walls and quiet moves",
        "lesson": [
            "The beginner's instinct is to flip as many discs as possible. It backfires: big flips leave "
            "the opponent many places to move and you very few. A player who runs out of safe moves has "
            "to play X- and C-squares and gives up the corners. Rose treats this as the key insight "
            "of the whole book.",
            "Frontier discs are discs next to an empty square. A connected group of your frontier discs "
            "is a wall: it shields the opponent's discs, gives him lots of options on the other side, "
            "and leaves you nothing to flip there. Discs completely surrounded by other discs are "
            "interior discs and are much healthier.",
            "A loud move creates many new frontier discs; a quiet move creates few and flips mostly "
            "interior discs. The ideal quiet move is almost like passing, and in Othello passing is "
            "often exactly what you want: each extra move you are forced to make tends to weaken you. "
            "A poison disc is one of your discs that would turn an otherwise quiet move into a loud one.",
            "Keep your options many and your opponent's few. That idea, mobility, is the thread "
            "running through the rest of the book.",
        ],
        "ideas": [
            "Fewer discs and more moves usually beats more discs and fewer moves.",
            "Quiet moves flip interior discs and create no new frontier.",
            "Walls give the opponent options; avoid building them.",
        ],
        "look_for": [
            "How many new frontier discs does each candidate create?",
            "How many moves will my opponent have afterwards?",
            "Is there a move that is almost like passing?",
        ],
        "drill": {"kinds": {"move": 0.6, "judge": 0.4}, "empties": (28, 46), "filter": "frontier_spread", "level": 10},
        "scrimmage": {"level": 3, "variety": 2, "threshold": 6,
                      "about": "The coach pauses only for loud moves that build walls and open options for Edax."},
    },
    {
        "id": "openings", "part": 1, "chapter": "4", "pages": "17–21",
        "title": "Playing the opening",
        "lesson": [
            "Think of the opening as lasting until someone takes an edge square. As a beginner there is "
            "little to gain from memorising lines: many different moves lead to balanced positions, and "
            "playing games teaches more. Play both colours, and always start in the same place (f5 is "
            "used throughout this app) so positions become familiar.",
            "White's second move is perpendicular, diagonal or parallel to Black's first. The first two "
            "are standard; the parallel is considered weaker. After that, the Chapter 3 ideas apply: "
            "play quietly and in the middle.",
            "What changes in the opening is the value of the centre. With few discs on the board, having "
            "your discs clustered in the middle matters, and sometimes a slightly louder move is right "
            "because it captures central discs and sets up quiet moves later. Typical errors are jutting "
            "out toward an edge away from the other discs, or handing the opponent an excellent quiet "
            "square.",
        ],
        "ideas": [
            "Stay central and compact; avoid moves that jut toward the edges.",
            "Quiet is still the default, but central discs are worth a little noise.",
            "Don't hand the opponent a perfect quiet reply.",
        ],
        "look_for": ["Does my move stay next to the other discs?", "What is my opponent's best quiet reply afterwards?"],
        "drill": {"kinds": {"move": 0.8, "judge": 0.2}, "empties": (46, 54), "level": 10},
        "scrimmage": {"level": 4, "variety": 1, "threshold": 5,
                      "about": "The coach pauses for loud opening moves that open up options for Edax."},
    },
    {
        "id": "edges", "part": 1, "chapter": "5", "pages": "23–30",
        "title": "Edges, tempo and pairs",
        "lesson": [
            "Nearly half the squares are edge squares, and Rose believes most games are decided by edge "
            "play. In the centre several moves are usually fine; on the edge there is often one clearly "
            "right move and a mistake costs a lot.",
            "A free move is an edge move the opponent cannot stop and that gives him no new options: it "
            "works like a pass. Making the opponent move first somewhere is called gaining a tempo, and "
            "it can be worth sacrificing a corner for. Don't give your opponent free moves.",
            "An unbalanced edge (a wing) has a disc on a C-square with a gap before the corner. It can "
            "be attacked: play next to it to threaten the corner, or wedge between two of the opponent's "
            "discs. A balanced edge, six discs between the corners, is usually the best edge to own.",
            "Mind the gap: a two-square gap is a pair, so if the opponent enters one square you answer "
            "in the other, while a one-square gap can simply be wedged into. Leave pairs alone until "
            "there is a reason to fill them. If you are being wiped out, an anchor disc on the edge "
            "(ideally an A-square) keeps you in the game.",
        ],
        "ideas": [
            "Free moves and tempo: make the opponent move first.",
            "Unbalanced edges invite corner attacks and wedges.",
            "Two-square gaps are pairs; one-square gaps are holes.",
        ],
        "look_for": [
            "Is there a move the opponent cannot prevent that gives him nothing?",
            "Does my edge move leave a one-square gap or create a wing?",
            "Can I attack an unbalanced edge?",
        ],
        "drill": {"kinds": {"move": 1.0}, "empties": (20, 40), "filter": "edge_choice", "level": 10},
        "scrimmage": {"level": 5, "variety": 1, "threshold": 5,
                      "about": "The coach pauses for edge mistakes: bad C-squares, edge moves that give a corner."},
    },
    {
        "id": "endgame", "part": 1, "chapter": "6", "pages": "31–39",
        "title": "Basic endgame strategy",
        "lesson": [
            "When you are ahead, win the simplest way. Keep your opponent out of safe moves and let "
            "him give up the corners; it is very easy to let a won game slip by being too clever. Often "
            "the cleanest technique is an interior sweep: rather than grabbing a corner, play moves that "
            "collect large numbers of stable interior discs while every reply is forced.",
            "Diagonal control means owning one of the long diagonals (a1–h8 or a8–h1). It lets you play "
            "X-squares on that diagonal without giving up a corner, and those moves usually gain tempo. "
            "Late in the game, access to the X-squares can decide who runs out of moves first. To take "
            "a corner from a diagonal the opponent controls you have to break the diagonal, ideally with "
            "a move that flips diagonally so it cannot simply be flipped back.",
            "A swindle happens when you move into a pair and the opponent has no legal move into the "
            "other square, so you get both. Watch for them on both sides.",
        ],
        "ideas": [
            "Ahead? Simple is best; keep the opponent out of moves.",
            "Interior sweeps beat corner grabs surprisingly often.",
            "Diagonal control makes X-squares safe; break the opponent's diagonal.",
        ],
        "look_for": ["Which of my moves leave the opponent only bad replies?", "Who controls each long diagonal?"],
        "drill": {"kinds": {"move": 0.8, "judge": 0.2}, "empties": (10, 18), "level": 12},
        "scrimmage": {"level": 6, "variety": 0, "threshold": 4,
                      "about": "The coach pauses for endgame mistakes that give corners or waste stable discs."},
    },
    {
        "id": "defense", "part": 1, "chapter": "7", "pages": "41–45",
        "title": "Playing defense",
        "lesson": [
            "Finding your own good moves is half of it; the other half is stopping your opponent from "
            "making his. There are three kinds of defensive move: flip some of his discs so he loses "
            "access to his good square; play on that square yourself; or make his good move less "
            "attractive, for example by making it flip a lot more.",
            "When the opponent is threatening a very good quiet move, the best move is usually a "
            "defensive one, even if it is a bit loud. The strongest moves do both jobs at once: they "
            "are quiet for you and they take something away from him.",
        ],
        "ideas": [
            "Three defences: take away access, occupy the square, spoil the move.",
            "A strong threat deserves a defensive answer, even a slightly loud one.",
            "Look for moves that are offence and defence together.",
        ],
        "look_for": ["What is my opponent's best move right now?", "Which of my moves takes it away?"],
        "drill": {"kinds": {"move": 0.7, "judge": 0.3}, "empties": (24, 40), "level": 10},
        "scrimmage": {"level": 6, "variety": 0, "threshold": 4,
                      "about": "The coach pauses for moves that hand Edax new options."},
    },
    # ------------------------------------------------------------------ Part II
    {
        "id": "parity", "part": 2, "chapter": "8", "pages": "47–55",
        "title": "Even number theory (parity)",
        "lesson": [
            "A region is a separate group of empty squares, usually around a corner. In a region with "
            "an even number of empties you would like to move last, so let the opponent go in first "
            "and follow him, flipping back what he just took. In practice: play into odd regions, leave "
            "even ones.",
            "With no passes, White gets the last move of the game (60 empties is even), so parity "
            "favours White by default. Black turns it around with a pass, or by having a region White "
            "cannot enter. It can be worth giving up a corner to keep parity in every region.",
            "Hyper parity: if your opponent has no legal move into an even region, he can never be "
            "forced to stop you going last there. The opposite trick is feeding the opponent: give him "
            "a legal move in a region so that you can regain the last move.",
        ],
        "ideas": [
            "Prefer odd regions; let the opponent open even ones.",
            "White has parity by default; Black needs a pass or an inaccessible region.",
            "Regions the opponent cannot enter are worth a lot.",
        ],
        "look_for": ["How many regions are there, and which are odd?", "Who can move into each region?"],
        "drill": {"kinds": {"move": 1.0}, "empties": (6, 14), "filter": "odd_region", "level": 14},
        "scrimmage": {"level": 7, "variety": 0, "threshold": 4,
                      "about": "The coach pauses for parity mistakes: opening an even region in the endgame."},
    },
    {
        "id": "tesuji1", "part": 2, "chapter": "9", "pages": "57–67",
        "title": "Tesuji I: corner attacks",
        "lesson": [
            "A tesuji is a stock good move for a recurring pattern. The corner attacks all work the same "
            "way: threaten a corner, so the opponent must either defend (often by making a move he "
            "hates) or give it up. When both choices are bad for him, the attack works.",
            "Patterns to know: forcing the opponent to build a wall; forcing him to flip your poison "
            "discs so your quiet move becomes available; gaining access to a vital square; grabbing a "
            "diagonal; the double corner attack, which nearly always wins the corner; the double "
            "unbalanced edge; and the Stoner trap, where an X-square is followed by an edge move that "
            "threatens the corner behind it.",
            "Don't get tunnel vision. Before launching an attack, ask what it costs and whether simply "
            "running the opponent out of moves is better.",
        ],
        "ideas": [
            "A corner threat is good when every defence hurts.",
            "Double corner attacks almost always win the corner.",
            "Check the price of the attack before you play it.",
        ],
        "look_for": ["Which move threatens a corner?", "How can the opponent answer, and does each answer hurt him?"],
        "drill": {"kinds": {"move": 1.0}, "empties": (14, 32), "filter": "corner_attack", "level": 12},
        "scrimmage": {"level": 7, "variety": 0, "threshold": 4,
                      "about": "The coach pauses for corner mistakes: giving a corner away or missing a corner attack's cost."},
    },
    {
        "id": "tesuji2", "part": 2, "chapter": "10", "pages": "69–77",
        "title": "Tesuji II: swindles",
        "lesson": [
            "A swindle is when you move into a pair and the opponent cannot answer in the other half, "
            "so you get both moves. Corner/C-square swindles are the most common and the most "
            "devastating; they are often set up by extracting the discs the opponent would need to "
            "reach the C-square, or by a corner attack that half-forces him to take the far corner.",
            "Swindles also happen between C- and A-squares and between A- and B-squares, and there are "
            "named ones worth recognising: the Boscov swindle, the four-in-the-corner swindle, the "
            "Landau maneuver, inviting a wedge, and the diagonal grab that wins three of four moves in "
            "a corner region.",
            "Before you play an X-square to attack an unbalanced edge, always check whether the opponent "
            "can swindle you in return.",
        ],
        "ideas": [
            "Swindle = both moves of a pair, because the opponent has no access.",
            "First remove the discs your opponent would need to reach the square.",
            "Check for swindles against you before every X-square.",
        ],
        "look_for": ["Which pairs exist, and who can move into each half?", "Can I take a corner without giving access to its C-square?"],
        "drill": {"kinds": {"move": 1.0}, "empties": (8, 26), "filter": "c_or_corner", "level": 12},
        "scrimmage": {"level": 7, "variety": 0, "threshold": 4,
                      "about": "The coach pauses for C-square and corner mistakes."},
    },
    {
        "id": "book", "part": 2, "chapter": "11", "pages": "79–87",
        "title": "Building an opening book",
        "lesson": [
            "Book openings are moves prepared before the game. Build yours from the games you actually "
            "play: record them, have the computer find your opening mistakes, and add one move at a "
            "time. Be selective: each extra move of depth multiplies the lines to remember. Rose's "
            "entire book when he won the World Championship was about 300 lines.",
            "Three principles help choose: prefer uncommon openings so the opponent is out of his "
            "book first; prefer openings that give you many good choices and the opponent few; and "
            "don't accept a position worse than about −4 just to be unusual. A perfectly played game "
            "seems to be a draw, so there is no forced win to find.",
            "Drills here use real tournament openings, graded by Edax and its opening book. "
            "Scrimmages start from the first moves of a real tournament game.",
        ],
        "ideas": [
            "Grow your book from your own games, one move at a time.",
            "Uncommon, easy to learn, never worse than −4.",
            "Record and review every opening you play.",
        ],
        "look_for": ["Have I seen this position before?", "Which move gives me many good follow-ups?"],
        "drill": {"kinds": {"move": 1.0}, "empties": (42, 52), "level": 12},
        "scrimmage": {"level": 8, "variety": 1, "threshold": 4, "opening_plies": 8,
                      "about": "Start from a real tournament opening; the coach pauses for loud moves that open options."},
    },
    {
        "id": "midgame", "part": 2, "chapter": "12", "pages": "89–97",
        "title": "Advanced midgame: shape",
        "lesson": [
            "Humans can't read as far ahead as programs, so they lean on good shape: patterns that tend "
            "to work out even when you can't calculate them. Cutting quietly through the middle is good "
            "shape; the shapes vulnerable to tesuji are bad shape. Good shapes need less reading; bad "
            "ones you must read out before you play them.",
            "To exploit an opponent's bad shape, imagine making several moves in a row while he passes. "
            "The move that lets you gain the most tempos in an area is usually the right one to start "
            "with. Learn to spot the hot spots each side wants to play to, and look for ways to set up "
            "a key move.",
            "Edges are bad shape in the long run but buy tempos in the midgame; holding adjacent edges "
            "is stronger than opposite edges. Losers hold more edge discs in the midgame on average, "
            "often because they grabbed edges in desperation. Take edges when you get offence or "
            "defence in return.",
        ],
        "ideas": [
            "Good shape works out without calculation; bad shape needs reading.",
            "Count tempos: how many moves in a row could I make here?",
            "Take an edge only for adequate compensation.",
        ],
        "look_for": ["Where are the hot spots for each side?", "Which move starts the longest run of my free moves?"],
        "drill": {"kinds": {"move": 0.6, "judge": 0.4}, "empties": (20, 38), "level": 12},
        "scrimmage": {"level": 8, "variety": 0, "threshold": 4,
                      "about": "The coach pauses for loud moves and edges taken without compensation."},
    },
    {
        "id": "counting", "part": 2, "chapter": "13", "pages": "99–110",
        "title": "Endgame counting",
        "lesson": [
            "In the last moves, counting is the only reliable guide. Start with the "
            "last two empties: count your discs, then for each candidate count the final score, either "
            "directly (one-step) or as a gain or loss (plus/minus). Cancellation, pairing discs gained "
            "with discs lost, makes counts faster when they are near each other.",
            "With more empties the opponent has choices too (branching). Count the most promising line "
            "first; you rarely need every sequence. Use parity to decide which lines to count, and look "
            "for winning lines without branches.",
            "Counting is also the best training for reading ahead and seeing the board in your mind. "
            "Start with two or three empties and work up. The Endgame puzzle card gives extra practice "
            "with exact answers.",
        ],
        "ideas": [
            "Count one side's discs; one-step is faster than two-step.",
            "Plus/minus for short counts, full disc counts for long ones.",
            "Count the best-looking line first; let parity prune.",
        ],
        "look_for": ["What does each move gain and lose?", "Which reply would the opponent choose?"],
        "drill": {"kinds": {"move": 0.7, "judge": 0.3}, "empties": (4, 10), "level": 14},
        "scrimmage": {"level": 8, "variety": 0, "threshold": 2,
                      "about": "The coach pauses for any endgame move that costs 2 discs or more."},
    },
    {
        "id": "masters", "part": 2, "chapter": "14 & 16", "pages": "111–116, 129–140",
        "title": "Thinking like a master",
        "lesson": [
            "Rose's advice for becoming an expert: practise intensely, count endgames to build "
            "visualisation, and record and review your games (use Analyze game after every scrimmage). "
            "Above all, study the games of strong players by putting yourself in one player's shoes: "
            "decide on your move, then look at what was actually played. Where the master's move is "
            "better than yours, you have found a blind spot.",
            "His favourite player to study is Hideshi Tamenori, five-time World Champion. The drills "
            "in this unit are positions from Tamenori's tournament games: pick your move and compare "
            "it with both Edax and what Tamenori played.",
            "Chapter 16 walks through a World Championship final and shows every idea in this course "
            "working together: opening choices, quiet moves, defence, edges, tempo and parity.",
        ],
        "ideas": [
            "Guess the master's move before you look.",
            "Review every game you play.",
            "Visualisation grows from counting endgames.",
        ],
        "look_for": ["What would Tamenori play here, and why?"],
        "drill": {"kinds": {"move": 1.0}, "empties": (16, 48), "player": "tamenori", "level": 12},
        "scrimmage": {"level": 10, "variety": 0, "threshold": 4,
                      "about": "A strong Edax. The coach pauses for loud moves, X-squares and corner gifts."},
    },
]

UNIT_BY_ID = {u["id"]: u for u in UNITS}
PART1 = [u["id"] for u in UNITS if u["part"] == 1]


def watch_tags(unit_id: str) -> tuple[str, ...]:
    return UNIT_CONCEPTS.get(unit_id, ())


def public() -> list[dict[str, Any]]:
    """The curriculum as the client needs it (served at /api/curriculum)."""
    out = []
    for u in UNITS:
        out.append({
            "id": u["id"], "part": u["part"], "chapter": u["chapter"], "pages": u["pages"], "title": u["title"],
            "lesson": u["lesson"], "ideas": u["ideas"], "look_for": u["look_for"],
            "drill_kinds": sorted(u["drill"]["kinds"]), "scrimmage": u["scrimmage"]["about"],
        })
    return out
