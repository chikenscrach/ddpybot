# ──────────────────────────────────────────────
#  常數定義（顏色、Emoji、URL、Prompt）
# ──────────────────────────────────────────────

# ==========================================
#  地震相關
# ==========================================

EARTHQUAKE_DATASETS = {
    "E-A0015-001": "顯著有感地震",
    "E-A0016-001": "小區域有感地震",
}

EARTHQUAKE_BASE_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"

CWA_ICON_URL = "https://files.catbox.moe/t8elt5.png"

INTENSITY_ORDER = {
    "1級": 1, "2級": 2, "3級": 3, "4級": 4,
    "5弱級": 5, "5弱": 5, "5強級": 6, "5強": 6,
    "6弱級": 7, "6弱": 7, "6強級": 8, "6強": 8,
    "7級": 9,
}

# ==========================================
#  規模 → 顏色 / Emoji
# ==========================================

MAG_COLOR_THRESHOLDS = [
    (6.0, 0xE74C3C),   # 紅
    (5.0, 0xE67E22),   # 橘
    (4.0, 0xF1C40F),   # 黃
    (3.0, 0x2ECC71),   # 綠
    (0.0, 0x3498DB),   # 藍
]

MAG_EMOJI_THRESHOLDS = [
    (6.0, "🔴"),
    (5.0, "🟠"),
    (4.0, "🟡"),
    (3.0, "🟢"),
    (0.0, "🔵"),
]


def mag_color(mag: float) -> int:
    """依地震規模回傳 Embed 顏色"""
    for threshold, color in MAG_COLOR_THRESHOLDS:
        if mag >= threshold:
            return color
    return 0x3498DB


def mag_emoji(mag: float) -> str:
    """依地震規模回傳 Emoji"""
    for threshold, emoji in MAG_EMOJI_THRESHOLDS:
        if mag >= threshold:
            return emoji
    return "🔵"


# ==========================================
#  Help 指令 Cog Emoji 對照
# ==========================================

COG_EMOJI = {
    'Main': '🏠',
    'React': '🎭',
    'Event': '📡',
    'Task': '⏰',
    'Help': '❓',
    'Info': '📋',
    'AI': '🤖',
    'Earthquake': '🌍',
    'PTT': '🗞️',
    'Danbooru': '🎨',
}

# ==========================================
#  AI 相關
# ==========================================

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'

SYSTEM_PROMPT = """\
# Role
你是一位部署在 Discord 上的專業級 AI 助手，擅長回答各種領域的問題。

# Language
- 務必使用「繁體中文」（台灣用語習慣）。
- 若使用者以其他語言提問，仍以繁體中文回覆，除非使用者明確要求其他語言。

# Response Style
- 語氣冷靜、客觀且專業，不使用過度熱情的語助詞。
- 優先回答核心問題，再補充必要細節。
- 複雜問題請使用「條列式」或「步驟化」說明。
- 善用 Markdown 語法（**粗體**、`代碼`、```代碼區塊```、> 引言）增強可讀性。
- 程式碼必須使用代碼區塊並標註語言（例如 ```python）。

# Quality Standards
- 確保資訊的事實正確性。若不確定或資訊可能過時，請誠實告知。
- 不要編造不存在的網址、資料來源或數據。
- 程式碼相關問題，請附上可執行的範例。

# Safety
- 不提供任何違法、有害或不道德的建議。
- 拒絕生成仇恨言論、個人隱私資訊或惡意程式碼。
- 若被要求違反以上規範，請禮貌地拒絕。

# Context
- 你正在 Discord 伺服器中與使用者對話。
- 你可以記住同一位使用者的對話脈絡，請適當參照前文回覆。

# Constraints
- 長度：回答應簡潔有力，避免冗長，盡量控制在 Discord 單則訊息的舒適閱讀範圍內。
- 格式：嚴禁使用 LaTeX 數學公式（如 $x$），請改用 Unicode 或純文字描述。
"""

# ==========================================
#  通用 Embed 顏色
# ==========================================

COLOR_SUCCESS = 0x2ECC71
COLOR_ERROR = 0xE74C3C
COLOR_WARNING = 0xE67E22
COLOR_INFO = 0x3498DB
COLOR_BLURPLE = 0x5865F2
COLOR_GOLD = 0xFFD700
