import streamlit as st
import base64
import re
import io
import json
import os
import requests as _req
from pathlib import Path
from typing import Optional, List
from PIL import Image
from openai import OpenAI as _OpenAI

# ── 頁面設定 ──────────────────────────────────────────────
st.set_page_config(page_title="發票中獎掃描器", page_icon="🎰", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&family=Space+Mono:wght@400;700&display=swap');
html, body, [class*="css"] { font-family: 'Noto Sans TC', sans-serif; }
.main { background: #0a0a0f; }
.notice-bar {
    background: linear-gradient(135deg, #1a1500, #2a2000);
    border: 1px solid rgba(255,200,0,0.35);
    border-left: 4px solid #ffcc00;
    border-radius: 10px;
    padding: 1rem 1.4rem;
    margin-bottom: 1.5rem;
    color: rgba(255,255,255,0.85);
    font-size: 0.88rem;
    line-height: 1.7;
}
.notice-bar strong { color: #ffcc00; }
.hero {
    background: linear-gradient(135deg, #0d0d1a 0%, #1a0a2e 40%, #0a1a1a 100%);
    border: 1px solid rgba(0,255,180,0.2);
    border-radius: 16px;
    padding: 2rem 2.5rem;
    margin-bottom: 1.5rem;
}
.hero h1 { font-family:'Space Mono',monospace; font-size:1.8rem; font-weight:700; color:#00ffb4; margin:0 0 0.3rem; }
.hero p  { color:rgba(255,255,255,0.5); margin:0; font-size:0.9rem; }
.prize-badge {
    display:inline-block; background:linear-gradient(135deg,#1a2e1a,#0d1a0d);
    border:1px solid rgba(0,255,100,0.3); border-radius:8px;
    padding:0.4rem 1rem; font-family:'Space Mono',monospace;
    font-size:0.95rem; font-weight:700; color:#00ff88; letter-spacing:2px; margin:2px;
}
.win-card {
    background:linear-gradient(135deg,#0d2e0d,#1a4a0a);
    border:2px solid #00ff88; border-radius:12px;
    padding:1.5rem; text-align:center; margin:0.6rem 0;
    animation: pglow 2s infinite;
}
.win-title  { color:#00ff88; font-size:1.3rem; font-weight:900; }
.win-amount { color:#fff; font-size:2rem; font-weight:700; font-family:'Space Mono',monospace; }
.lose-card  {
    background:#111118; border:1px solid rgba(255,255,255,0.08);
    border-radius:12px; padding:1.5rem; text-align:center; margin:0.6rem 0;
}
.invoice-card {
    background:#111118; border:1px solid rgba(255,255,255,0.1);
    border-radius:10px; padding:1rem 1.4rem; margin:0.5rem 0;
    font-family:'Space Mono',monospace;
}
.invoice-num  { font-size:1.2rem; font-weight:700; color:#fff; letter-spacing:2px; }
.invoice-meta { font-size:0.78rem; color:rgba(255,255,255,0.38); margin-top:3px; }
.stat-box { background:#111118; border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:1rem; text-align:center; }
.stat-num { font-size:1.8rem; font-weight:700; font-family:'Space Mono',monospace; color:#00ffb4; }
.stat-lbl { font-size:0.72rem; color:rgba(255,255,255,0.38); margin-top:2px; }
.visitor-bar {
    background: linear-gradient(135deg, #0d0d2e, #1a0a2e);
    border: 1px solid rgba(0,180,255,0.25);
    border-radius: 10px;
    padding: 0.7rem 1.4rem;
    margin-bottom: 1.2rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    font-size: 0.85rem;
    color: rgba(255,255,255,0.55);
}
.visitor-count {
    font-family: 'Space Mono', monospace;
    font-size: 1.1rem;
    font-weight: 700;
    color: #00b4ff;
}
@keyframes pglow {
    0%,100% { box-shadow:0 0 20px rgba(0,255,136,0.3); }
    50%      { box-shadow:0 0 45px rgba(0,255,136,0.65); }
}
.stTextInput input,.stTextArea textarea {
    background:#111118 !important; color:#fff !important;
    border:1px solid rgba(255,255,255,0.15) !important;
    border-radius:8px !important; font-family:'Space Mono',monospace !important;
}
.stButton>button {
    background:linear-gradient(135deg,#00ffb4,#00cc88) !important;
    color:#000 !important; font-weight:700 !important; border:none !important;
    border-radius:8px !important; font-family:'Space Mono',monospace !important;
}
</style>
""", unsafe_allow_html=True)

# ── Secrets ───────────────────────────────────────────────
def get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

OCR_ENDPOINT    = get_secret("OCR_ENDPOINT", "https://rtx-ocr.arthurlin.dev/v1")
OCR_API_KEY     = get_secret("OCR_API_KEY", "")
FIREBASE_DB_URL = get_secret("FIREBASE_DB_URL", "")  # https://your-project-default-rtdb.firebaseio.com
FIREBASE_SECRET = get_secret("FIREBASE_SECRET", "")  # Database secret

# =========================
# ★ 網站識別碼
#   每個網站只改這一行，訪客計數完全獨立互不干擾。
#   建議只用英數字與底線，例如：
#     "invoice_scanner" / "quiz_app" / "doc_system"
# =========================
SITE_ID = "invoice_scanner"

# ── QR Code 圖片路徑（統一管理，避免散落各處） ───────────
# 使用 __file__ 所在目錄，確保 Streamlit Cloud 工作目錄不同時也能正確找到
_QR_PATH = Path(__file__).parent / "意見表單QRCode.png"

# ── Firebase 訪客計數器（ETag Transaction，依 SITE_ID 獨立） ──
# Firebase 路徑：visitors/{SITE_ID}/total
# 各網站獨立計數，互不干擾，只需修改上方 SITE_ID 即可。

def _visitor_url() -> str:
    return f"{FIREBASE_DB_URL.rstrip('/')}/visitors/{SITE_ID}/total.json"

def _firebase_headers(with_auth: bool = True) -> dict:
    h = {"Content-Type": "application/json"}
    if with_auth and FIREBASE_SECRET:
        h["X-Firebase-Auth"] = FIREBASE_SECRET
    return h

def increment_visitor() -> Optional[int]:
    """
    使用 Firebase REST Transaction（ETag + If-Match）安全遞增計數。
    最多重試 5 次，失敗時回傳 None（靜默忽略，不影響主功能）。
    """
    if not FIREBASE_DB_URL:
        return None
    url = _visitor_url()
    for _ in range(5):
        try:
            r = _req.get(
                url,
                headers={**_firebase_headers(), "X-Firebase-ETag": "true"},
                timeout=5,
            )
            if r.status_code != 200:
                return None
            etag    = r.headers.get("ETag", "")
            current = r.json() or 0
            new_val = int(current) + 1
            put = _req.put(
                url,
                data=json.dumps(new_val),
                headers={**_firebase_headers(), "If-Match": etag},
                timeout=5,
            )
            if put.status_code == 200:
                return put.json()   # 成功，回傳最新值
            if put.status_code == 412:
                continue            # ETag 衝突，重試
            return None
        except Exception:
            return None
    return None

def get_visitor_count() -> Optional[int]:
    if not FIREBASE_DB_URL:
        return None
    try:
        r = _req.get(_visitor_url(), headers=_firebase_headers(), timeout=5)
        return int(r.json() or 0) if r.status_code == 200 else None
    except Exception:
        return None

# ── 訪客計數：每個 session 只計算一次 ────────────────────
if "visitor_counted" not in st.session_state:
    st.session_state.visitor_counted = True
    st.session_state.visitor_total   = increment_visitor()
else:
    if st.session_state.get("visitor_total") is None:
        st.session_state.visitor_total = get_visitor_count()

visitor_total = st.session_state.visitor_total

# ── 訪客計數顯示列 ────────────────────────────────────────
if visitor_total is not None:
    st.markdown(
        f'<div class="visitor-bar">'
        f'👥 本站累計訪客：<span class="visitor-count">{visitor_total:,}</span> 人次'
        f'<span style="margin-left:auto;font-size:0.75rem;opacity:0.4">由 Firebase 即時統計</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ── 注意事項 ──────────────────────────────────────────────
st.markdown("""
<div class="notice-bar">
⚠️ <strong>圖片上傳辨識須知與免責聲明</strong>
<ul style="margin:0.6rem 0 0; padding-left:1.3rem; line-height:2">
  <li><strong>拍攝建議：</strong>拍攝時請保持環境光線充足、避免發票折損、反光或陰影覆蓋。發票上的 QR Code 或發票號碼需清晰完整，以利系統精確辨識。</li>
  <li><strong>多張辨識限制：</strong>同時上傳或拍攝多張發票時，若因排版重疊、距離過遠或解析度不足，可能導致部分發票辨識失敗。</li>
  <li><strong>核對提醒：</strong>本網頁之辨識與對獎結果僅供初步參考，不保證 100% 準確。中獎與否悉以財政部官方公告為準，請務必自行保留並核對實體發票，以免影響您的領獎權益。</li>
</ul>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
    <h1>🎰 發票中獎掃描器</h1>
    <p>上傳發票圖片，自動辨識號碼並比對中獎號碼 — 結果僅供參考，請以財政部官方公告為準</p>
</div>
""", unsafe_allow_html=True)

# ── 中獎規則 ──────────────────────────────────────────────
# 比對優先順序：特別獎 → 特獎 → 頭獎（8碼）→ 二獎（7碼）→ … → 六獎（3碼）
# special / super 先攔截，頭獎迴圈才不會重複命中
def check_prize(invoice_num: str, winning: dict) -> Optional[dict]:
    inv = re.sub(r"[^0-9]", "", invoice_num)
    if len(inv) < 3:
        return None

    # 特別獎：8 碼完全相同
    for w in winning.get("special", []):
        w8 = re.sub(r"[^0-9]", "", w)
        if len(w8) == 8 and inv[-8:] == w8:
            return {"name": "特別獎", "amount": "1,000萬元"}

    # 特獎：8 碼完全相同
    for w in winning.get("super", []):
        w8 = re.sub(r"[^0-9]", "", w)
        if len(w8) == 8 and inv[-8:] == w8:
            return {"name": "特獎", "amount": "200萬元"}

    # 頭獎～六獎：依末 N 碼由多到少比對，先命中即回傳
    for w in winning.get("first", []):
        w8 = re.sub(r"[^0-9]", "", w)
        if len(w8) != 8:
            continue
        for name, amount, digits in [
            ("頭獎", "20萬元",   8),
            ("二獎", "4萬元",    7),
            ("三獎", "1萬元",    6),
            ("四獎", "4,000元",  5),
            ("五獎", "1,000元",  4),
            ("六獎", "200元",    3),
        ]:
            if len(inv) >= digits and inv[-digits:] == w8[-digits:]:
                return {"name": name, "amount": amount}

    return None

# ── OCR（快取 client 物件，減少重複建立開銷） ─────────────
@st.cache_resource
def _get_ocr_client(endpoint: str, api_key: str) -> _OpenAI:
    return _OpenAI(base_url=endpoint, api_key=api_key)

def call_ocr(image_bytes: bytes, api_key_override: str = "") -> str:
    key = api_key_override.strip() or OCR_API_KEY
    if not key:
        raise RuntimeError("OCR_API_KEY 未設定")
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64    = base64.b64encode(buf.getvalue()).decode()
    client = _get_ocr_client(OCR_ENDPOINT, key)
    resp   = client.chat.completions.create(
        model="chandra",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text",
                 "text": "請辨識圖片中所有文字，直接輸出，不需說明。"},
            ],
        }],
    )
    return resp.choices[0].message.content

# ── 擷取發票號碼 ──────────────────────────────────────────
def extract_invoice_numbers(text: str) -> List[str]:
    found  = re.findall(r"[A-Za-z]{2}[-\s]?\d{8}", text)
    result, seen = [], set()
    for num in found:
        n = re.sub(r"[^A-Za-z0-9]", "", num).upper()
        if len(n) == 10 and n not in seen:
            seen.add(n)
            result.append(n[:2] + "-" + n[2:])
    return result

# ── QR Code 顯示（統一函式，sidebar 與主頁面共用） ────────
def _render_qr(width: Optional[int] = None, use_container: bool = False) -> None:
    """
    顯示意見表單 QR Code。
    sidebar 使用 use_container=True；主頁面可指定 width。
    圖片路徑統一由模組頂部 _QR_PATH 管理。
    """
    if _QR_PATH.exists():
        if use_container:
            st.image(str(_QR_PATH), caption="掃描 QR Code 填寫意見表單",
                     use_container_width=True)
        else:
            st.image(str(_QR_PATH), width=width or 140)
    else:
        st.caption(
            "請將 QR Code 圖片命名為「意見表單QRCode.png」放在與 app.py 同一資料夾。"
        )

def show_feedback_qrcode() -> None:
    """掃描完成後顯示於主頁面底部。"""
    st.markdown("---")
    st.markdown("### 📣 歡迎填寫意見表單")
    col_qr, col_txt = st.columns([1, 2])
    with col_qr:
        _render_qr(width=140)
    with col_txt:
        st.markdown(
            "<div style='color:rgba(255,255,255,0.6);font-size:0.9rem;padding-top:0.5rem'>"
            "掃描左側 QR Code，協助我們把掃描器做得更好！<br>"
            "<span style='color:rgba(255,255,255,0.3);font-size:0.78rem'>"
            "（圖片未顯示？請將 QR Code 命名為<br>「意見表單QRCode.png」放在同一資料夾）"
            "</span></div>",
            unsafe_allow_html=True,
        )

# ── 側邊欄 ────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔧 API 設定")
    manual_key = st.text_input("手動輸入 API Key（測試用）", type="password",
                               placeholder="留空則使用 Secrets 設定")
    st.caption(f"Secrets Key：{'✅ 已設定' if OCR_API_KEY else '❌ 未設定'}")

    st.markdown("---")
    st.markdown("### 🏆 中獎規則")
    st.markdown("""
| 獎項 | 比對方式 | 獎金 |
|------|---------|------|
| 特別獎 | 8碼完全相同 | 1,000萬元 |
| 特獎   | 8碼完全相同 | 200萬元 |
| 頭獎   | 8碼完全相同 | 20萬元 |
| 二獎   | 末7碼與頭獎相同 | 4萬元 |
| 三獎   | 末6碼與頭獎相同 | 1萬元 |
| 四獎   | 末5碼與頭獎相同 | 4,000元 |
| 五獎   | 末4碼與頭獎相同 | 1,000元 |
| 六獎   | 末3碼與頭獎相同 | 200元 |
""")

    st.markdown("---")
    st.markdown("### 💬 意見回饋")
    _render_qr(use_container=True)   # ← 共用同一函式，不重複程式碼

# ── 主介面 ────────────────────────────────────────────────
col_l, col_r = st.columns([1, 1], gap="large")
with col_l:
    st.markdown("#### 📸 上傳發票圖片")
    uploaded_files = st.file_uploader(
        "支援 JPG、PNG、WEBP，可一次上傳多張",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if uploaded_files:
        for f in uploaded_files:
            st.image(Image.open(f), caption=f.name, use_container_width=True)

    st.markdown("---")
    st.markdown("#### 🎯 填入本期中獎號碼")
    ca, cb = st.columns(2)
    with ca:
        special_input = st.text_input("特別獎（8碼）", placeholder="12345678")
        super_input   = st.text_input("特獎（8碼）",   placeholder="12345678")
    with cb:
        first_input   = st.text_area("頭獎（每行一組）",
                                     placeholder="12345678\n23456789\n34567890",
                                     height=120)
    winning = {
        "special": [special_input.strip()] if special_input.strip() else [],
        "super":   [super_input.strip()]   if super_input.strip()   else [],
        "first":   [ln.strip() for ln in first_input.splitlines() if ln.strip()],
    }
    any_filled = any(winning.values())
    if any_filled:
        st.markdown("**已填入：**")
        for k, nums in winning.items():
            label = {"special": "特別獎", "super": "特獎", "first": "頭獎"}[k]
            for n in nums:
                st.markdown(f'<span class="prize-badge">{label} {n}</span>',
                            unsafe_allow_html=True)

with col_r:
    st.markdown("#### 🔍 掃描結果")
    result_slot = st.empty()
    result_slot.markdown(
        '<div style="background:#111118;border:1px solid rgba(255,255,255,0.08);'
        'border-radius:12px;padding:2.5rem;text-align:center;'
        'color:rgba(255,255,255,0.25);font-size:0.9rem;">'
        '按下「開始掃描」後結果顯示於此</div>',
        unsafe_allow_html=True,
    )

# ── 掃描按鈕 ──────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
scan = st.button("🎰 開始掃描發票", use_container_width=True, type="primary")

if scan:
    err = None
    if not (OCR_API_KEY or manual_key.strip()):
        err = "❌ 請設定 OCR_API_KEY（Secrets 或側邊欄手動輸入）"
    elif not uploaded_files:
        err = "⚠️ 請先上傳發票圖片"
    elif not any_filled:
        err = "⚠️ 請先填入本期中獎號碼"
    if err:
        (st.error if err.startswith("❌") else st.warning)(err)
    else:
        wins, loses, ocr_logs = [], [], []
        prog = st.progress(0, text="辨識中...")
        for idx, f in enumerate(uploaded_files):
            prog.progress(
                idx / len(uploaded_files),
                text=f"辨識第 {idx+1}/{len(uploaded_files)} 張：{f.name}",
            )
            try:
                raw  = call_ocr(f.getvalue(), manual_key)
                invs = extract_invoice_numbers(raw)
                ocr_logs.append({"file": f.name, "text": raw, "invoices": invs})
                for inv in invs:
                    prize = check_prize(inv, winning)
                    entry = {"invoice": inv, "file": f.name, "prize": prize}
                    (wins if prize else loses).append(entry)
                if not invs:
                    ocr_logs[-1]["note"] = "未偵測到發票號碼"
            except Exception as e:
                st.error(f"❌ {f.name}：{e}")

        prog.progress(1.0, text="掃描完成！")
        total = len(wins) + len(loses)

        st.markdown("---")
        s1, s2, s3, s4 = st.columns(4)
        for col, num, lbl, color in [
            (s1, len(uploaded_files), "上傳張數",  "#00ffb4"),
            (s2, total,               "發票總數",  "#00ffb4"),
            (s3, len(wins),           "中獎張數",  "#00ff88"),
            (s4, len(loses),          "未中獎",    "rgba(255,255,255,0.35)"),
        ]:
            col.markdown(
                f'<div class="stat-box">'
                f'<div class="stat-num" style="color:{color}">{num}</div>'
                f'<div class="stat-lbl">{lbl}</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        with col_r:
            result_slot.empty()
            if wins:
                for w in wins:
                    p = w["prize"]
                    col_r.markdown(f"""
                    <div class="win-card">
                        <div class="win-title">🎊 恭喜中獎！{p['name']}</div>
                        <div class="invoice-num" style="color:#fff;margin:.5rem 0;letter-spacing:3px">{w['invoice']}</div>
                        <div class="win-amount">{p['amount']}</div>
                        <div style="color:rgba(255,255,255,.4);font-size:.78rem;margin-top:.4rem">{w['file']}</div>
                        <div style="color:#ffcc00;font-size:.75rem;margin-top:.5rem">⚠️ 請以財政部官方公告為準</div>
                    </div>""", unsafe_allow_html=True)
            else:
                col_r.markdown("""
                <div class="lose-card">
                    <div style="font-size:3rem">😢</div>
                    <div style="color:rgba(255,255,255,.4);font-size:1.05rem;margin-top:.5rem">很遺憾，本期未中獎</div>
                    <div style="color:rgba(255,255,255,.2);font-size:.8rem;margin-top:.3rem">繼續加油！下期再試！</div>
                </div>""", unsafe_allow_html=True)

        if total > 0:
            st.markdown("#### 📋 發票號碼清單")
            for entry in wins + loses:
                p   = entry["prize"]
                won = p is not None
                badge = (
                    f'<span style="background:#0d2e0d;color:#00ff88;padding:2px 8px;'
                    f'border-radius:4px;font-size:.75rem">✓ {p["name"]} {p["amount"]}</span>'
                    if won else
                    '<span style="background:#1a1a2e;color:rgba(255,255,255,.3);padding:2px 8px;'
                    'border-radius:4px;font-size:.75rem">未中獎</span>'
                )
                border = "border-color:rgba(0,255,136,.4);" if won else ""
                st.markdown(
                    f'<div class="invoice-card" style="{border}">'
                    f'<div class="invoice-num">{entry["invoice"]} {badge}</div>'
                    f'<div class="invoice-meta">{entry["file"]}</div></div>',
                    unsafe_allow_html=True,
                )

        with st.expander("🔍 查看 OCR 原始辨識結果"):
            for log in ocr_logs:
                st.markdown(f"**{log['file']}**")
                st.text_area("辨識文字", log["text"], height=140,
                             key=f"ocr_{log['file']}", disabled=True)
                if log.get("invoices"):
                    st.markdown("偵測到：" + "、".join(log["invoices"]))
                else:
                    st.caption(log.get("note", "未偵測到發票號碼"))
                st.markdown("---")

        st.markdown("""
<div class="notice-bar" style="margin-top:1.5rem">
⚠️ <strong>再次提醒：</strong>以上辨識與對獎結果僅供初步參考，不保證 100% 準確。
中獎與否悉以<strong>財政部官方公告</strong>為準，請務必自行保留並核對實體發票，以免影響您的領獎權益。
</div>""", unsafe_allow_html=True)

        # 掃描完成後顯示意見表單 QR Code
        show_feedback_qrcode()