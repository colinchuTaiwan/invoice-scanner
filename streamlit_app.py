"""
invoice_scanner.py — 發票中獎掃描器（強化版）

改善內容：
1. 強化發票號碼擷取
2. 支援多張重疊發票
3. 修正 OCR 空白 / 換行問題
4. 修正 OCR 英數誤判
5. 可抓：
   AB-12345678
   AB12345678
   A B 12345678
"""

import streamlit as st
import base64
import re
import io
from PIL import Image, ImageEnhance, ImageFilter
from openai import OpenAI as _OpenAI


# ─────────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="發票中獎掃描器",
    page_icon="🎰",
    layout="wide"
)

st.title("🎰 發票中獎掃描器")
st.caption("上傳發票圖片，自動辨識所有發票號碼")


# ─────────────────────────────────────────────
# Secrets
# ─────────────────────────────────────────────
def get_secret(key, default=""):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


OCR_ENDPOINT = get_secret(
    "OCR_ENDPOINT",
    "https://rtx-ocr.arthurlin.dev/v1"
)

OCR_API_KEY = get_secret("OCR_API_KEY", "")


# ─────────────────────────────────────────────
# OCR 前處理（提升辨識率）
# ─────────────────────────────────────────────
def preprocess_image(image_bytes: bytes) -> bytes:

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # 放大
    w, h = img.size
    img = img.resize((w * 2, h * 2))

    # 銳利化
    img = img.filter(ImageFilter.SHARPEN)

    # 增加對比
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.8)

    buf = io.BytesIO()
    img.save(buf, format="PNG")

    return buf.getvalue()


# ─────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────
def call_ocr(image_bytes: bytes, api_key_override=""):

    key = api_key_override.strip() or OCR_API_KEY

    if not key:
        raise RuntimeError("OCR_API_KEY 未設定")

    processed = preprocess_image(image_bytes)

    b64 = base64.b64encode(processed).decode()

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

發票格式：
兩個英文字母 + 八位數字

例如：
AB-12345678
CD12345678

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


# ─────────────────────────────────────────────
# 強化版發票號碼擷取
# ─────────────────────────────────────────────
def extract_invoice_numbers(text: str):

    # OCR 常見誤判修正
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

    # 移除特殊符號
    t = re.sub(r"[|<>]", " ", t)

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

                # A B 12345678
                if len(groups[0]) == 1 and len(groups[1]) == 1:
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

                if re.fullmatch(r"[A-Z]{2}\d{8}", inv):
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


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────
st.markdown("### 📸 上傳發票圖片")

uploaded_files = st.file_uploader(
    "支援多張 JPG / PNG",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True
)

manual_key = st.text_input(
    "手動輸入 OCR API Key（可留空）",
    type="password"
)

scan = st.button("🎯 開始掃描")


# ─────────────────────────────────────────────
# 掃描
# ─────────────────────────────────────────────
if scan:

    if not uploaded_files:
        st.warning("請先上傳圖片")
        st.stop()

    if not (OCR_API_KEY or manual_key.strip()):
        st.error("請設定 OCR_API_KEY")
        st.stop()

    all_invoices = []

    progress = st.progress(0)

    for idx, f in enumerate(uploaded_files):

        progress.progress(
            (idx + 1) / len(uploaded_files)
        )

        st.write(f"辨識中：{f.name}")

        try:

            raw = call_ocr(
                f.getvalue(),
                manual_key
            )

            invoices = extract_invoice_numbers(raw)

            st.markdown("#### OCR 原始結果")
            st.code(raw)

            if invoices:

                st.success(
                    f"找到 {len(invoices)} 張發票"
                )

                for inv in invoices:

                    st.markdown(
                        f"### 🎫 {inv}"
                    )

                    all_invoices.append(inv)

            else:

                st.warning("未找到發票號碼")

        except Exception as e:

            st.error(str(e))

    # 去重
    all_invoices = list(dict.fromkeys(all_invoices))

    st.markdown("---")

    st.markdown("# 📋 所有發票號碼")

    if all_invoices:

        for inv in all_invoices:
            st.code(inv)

        st.success(
            f"總共找到 {len(all_invoices)} 張發票"
        )

    else:

        st.error("沒有辨識到任何發票")