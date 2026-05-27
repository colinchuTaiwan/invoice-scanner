"""
invoice_scanner.py — 發票中獎掃描器（完整強化版）

功能：
1. OCR 辨識所有發票
2. 自動抓取發票號碼
3. 支援多張重疊發票
4. 可輸入中獎號碼
5. 自動對獎
6. 顯示中獎結果
"""

import streamlit as st
import base64
import re
import io

from PIL import (
    Image,
    ImageEnhance,
    ImageFilter
)

from openai import OpenAI as _OpenAI


# ─────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────
st.set_page_config(
    page_title="發票中獎掃描器",
    page_icon="🎰",
    layout="wide"
)

st.title("🎰 發票中獎掃描器")
st.caption("OCR 自動辨識所有發票號碼並對獎")


# ─────────────────────────────────────
# Secrets
# ─────────────────────────────────────
def get_secret(key, default=""):

    try:
        return st.secrets.get(key, default)

    except Exception:
        return default


OCR_ENDPOINT = get_secret(
    "OCR_ENDPOINT",
    "https://rtx-ocr.arthurlin.dev/v1"
)

OCR_API_KEY = get_secret(
    "OCR_API_KEY",
    ""
)


# ─────────────────────────────────────
# OCR 前處理
# ─────────────────────────────────────
def preprocess_image(image_bytes: bytes):

    img = Image.open(
        io.BytesIO(image_bytes)
    ).convert("RGB")

    # 放大
    w, h = img.size

    img = img.resize(
        (w * 2, h * 2)
    )

    # 銳化
    img = img.filter(
        ImageFilter.SHARPEN
    )

    # 對比
    enhancer = ImageEnhance.Contrast(img)

    img = enhancer.enhance(1.8)

    buf = io.BytesIO()

    img.save(buf, format="PNG")

    return buf.getvalue()


# ─────────────────────────────────────
# OCR
# ─────────────────────────────────────
def call_ocr(image_bytes: bytes, api_key_override=""):

    key = api_key_override.strip() or OCR_API_KEY

    if not key:
        raise RuntimeError("OCR_API_KEY 未設定")

    processed = preprocess_image(image_bytes)

    b64 = base64.b64encode(
        processed
    ).decode()

    client = _OpenAI(
        base_url=OCR_ENDPOINT,
        api_key=key
    )

    resp = client.chat.completions.create(
        model="chandra",
        messages=[
            {
                "role": "user",
                "content": [

                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64}"
                        }
                    },

                    {
                        "type": "text",
                        "text": """
請找出圖片中所有台灣電子發票號碼。
發票號碼可能歪斜,或被遮蔽部分英文,只要找完整的8位數字
格式：
兩個英文字母+8位數字(如ab 12345678 or ab-12345678)

只輸出發票號碼。
一行一個。
不要解釋。
"""
                    }
                ]
            }
        ]
    )

    return resp.choices[0].message.content


# ─────────────────────────────────────
# 擷取發票號碼
# ─────────────────────────────────────
def extract_invoice_numbers(text: str):

    t = text.upper()

    replace_map = {
        "－": "-",
        "–": "-",
        "—": "-",
        "Ｏ": "0",
        "Ｑ": "0",
        "I": "1",
        "Ｉ": "1",
        "ｌ": "1",
    }

    for k, v in replace_map.items():
        t = t.replace(k, v)

    patterns = [

        # AB-12345678
        r"\b([A-Z]{2})\s*[-]?\s*(\d{8})\b",

        # A B 12345678
        r"\b([A-Z])\s+([A-Z])\s*(\d{8})\b",

        # AB 1234 5678
        r"\b([A-Z]{2})\s*(\d{4})\s*(\d{4})\b",

        # OCR 多空白
        r"\b([A-Z]{2})[\s\-]*(\d[\d\s]{7,20})\b",
    ]

    found = []

    for p in patterns:

        for m in re.finditer(p, t):

            groups = m.groups()

            if len(groups) == 2:

                prefix = groups[0]
                digits = groups[1]

            elif len(groups) == 3:

                if len(groups[0]) == 1:

                    prefix = groups[0] + groups[1]
                    digits = groups[2]

                else:

                    prefix = groups[0]
                    digits = groups[1] + groups[2]

            else:
                continue

            digits = re.sub(r"\D", "", digits)

            if len(digits) >= 8:

                inv = prefix + digits[:8]

                if re.fullmatch(
                    r"[A-Z]{2}\d{8}",
                    inv
                ):
                    found.append(inv)

    # 去重
    result = []
    seen = set()

    for n in found:

        if n not in seen:

            seen.add(n)

            result.append(
                f"{n[:2]}-{n[2:]}"
            )

    return result


# ─────────────────────────────────────
# 對獎
# ─────────────────────────────────────
def check_prize(invoice_num, winning):

    inv = re.sub(r"\D", "", invoice_num)

    # 特別獎
    for w in winning["special"]:

        if inv == w:
            return ("特別獎", "1000萬元")

    # 特獎
    for w in winning["super"]:

        if inv == w:
            return ("特獎", "200萬元")

    # 頭獎
    for w in winning["first"]:

        if inv == w:
            return ("頭獎", "20萬元")

        if inv[-7:] == w[-7:]:
            return ("二獎", "4萬元")

        if inv[-6:] == w[-6:]:
            return ("三獎", "1萬元")

        if inv[-5:] == w[-5:]:
            return ("四獎", "4000元")

        if inv[-4:] == w[-4:]:
            return ("五獎", "1000元")

        if inv[-3:] == w[-3:]:
            return ("六獎", "200元")

    return None


# ─────────────────────────────────────
# 上傳區
# ─────────────────────────────────────
st.markdown("## 📸 上傳發票圖片")

uploaded_files = st.file_uploader(
    "支援 JPG / PNG",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True
)

manual_key = st.text_input(
    "手動輸入 OCR API Key",
    type="password"
)


# ─────────────────────────────────────
# 中獎號碼
# ─────────────────────────────────────
st.markdown("## 🎯 輸入中獎號碼")

col1, col2 = st.columns(2)

with col1:

    special_input = st.text_input(
        "特別獎（1000萬）",
        placeholder="12345678"
    )

    super_input = st.text_input(
        "特獎（200萬）",
        placeholder="12345678"
    )

with col2:

    first_input = st.text_area(
        "頭獎（每行一組）",
        placeholder="""
12345678
87654321
11223344
"""
    )


winning = {
    "special": [],
    "super": [],
    "first": []
}

if special_input.strip():
    winning["special"].append(
        special_input.strip()
    )

if super_input.strip():
    winning["super"].append(
        super_input.strip()
    )

if first_input.strip():

    lines = first_input.splitlines()

    for line in lines:

        line = line.strip()

        if line:
            winning["first"].append(line)


# ─────────────────────────────────────
# 掃描按鈕
# ─────────────────────────────────────
scan = st.button("🎰 開始掃描")


# ─────────────────────────────────────
# 開始掃描
# ─────────────────────────────────────
if scan:

    if not uploaded_files:

        st.warning("請先上傳圖片")
        st.stop()

    if not any(winning.values()):

        st.warning("請輸入中獎號碼")
        st.stop()

    if not (OCR_API_KEY or manual_key.strip()):

        st.error("請設定 OCR_API_KEY")
        st.stop()

    all_results = []

    progress = st.progress(0)

    for idx, f in enumerate(uploaded_files):

        progress.progress(
            (idx + 1) / len(uploaded_files)
        )

        st.markdown(f"# 🔍 {f.name}")

        try:

            raw = call_ocr(
                f.getvalue(),
                manual_key
            )

            invoices = extract_invoice_numbers(raw)

            st.markdown("### OCR 原始結果")

            st.code(raw)

            if not invoices:

                st.warning("未找到發票號碼")
                continue

            for inv in invoices:

                prize = check_prize(
                    inv,
                    winning
                )

                all_results.append({
                    "invoice": inv,
                    "prize": prize
                })

        except Exception as e:

            st.error(str(e))


    # ─────────────────────────────
    # 顯示結果
    # ─────────────────────────────
    st.markdown("---")

    st.markdown("# 📋 掃描結果")

    if not all_results:

        st.error("沒有找到任何發票")
        st.stop()

    win_count = 0

    for item in all_results:

        inv = item["invoice"]

        prize = item["prize"]

        if prize:

            win_count += 1

            name, amount = prize

            st.success(
                f"🎉 {inv} 中獎！"
            )

            st.markdown(
                f"""
### 🏆 {name}
### 💰 {amount}
"""
            )

        else:

            st.write(f"❌ {inv} 未中獎")

    st.markdown("---")

    st.markdown(
        f"""
# 🎯 統計

- 發票總數：{len(all_results)}
- 中獎張數：{win_count}
- 未中獎：{len(all_results) - win_count}
"""
    )