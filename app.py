
import io
import os
import tempfile
import uuid
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps
from gradio_client import Client, handle_file

try:
    from supabase import create_client
except Exception:
    create_client = None

# ============================================================
# APP CONFIG
# ============================================================

st.set_page_config(
    page_title="Her Closet",
    page_icon="🎀",
    layout="wide",
)

st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(180deg, #fff9fc 0%, #fff4f8 100%);
        }

        h1, h2, h3 {
            color: #4a3442;
        }

        .soft-card {
            background: rgba(255,255,255,0.92);
            border: 1px solid #f0d9e4;
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 10px 30px rgba(116, 66, 90, 0.08);
        }

        div.stButton > button {
            border-radius: 999px;
            border: 1px solid #e8bfd2;
            background: white;
        }

        div.stButton > button:hover {
            border-color: #d68caf;
            color: #9c4f73;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

LOCAL_ROOT = Path("closet")
LOCAL_BASE = Path("base_photo.png")

for folder in ["tops", "bottoms", "dresses"]:
    (LOCAL_ROOT / folder).mkdir(parents=True, exist_ok=True)

BUCKET = "digital-closet"

CATEGORY_LABELS = {
    "tops": "👚 Tops",
    "bottoms": "👖 Bottoms",
    "dresses": "👗 Dresses",
}

# ============================================================
# HELPERS
# ============================================================

def get_secret(name: str):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = get_secret("SUPABASE_SERVICE_KEY")


@st.cache_resource
def get_supabase():
    if not (SUPABASE_URL and SUPABASE_SERVICE_KEY and create_client):
        return None

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    try:
        client.storage.get_bucket(BUCKET)
    except Exception:
        try:
            client.storage.create_bucket(
                BUCKET,
                options={"public": False},
            )
        except Exception:
            pass

    return client


supabase = get_supabase()
CLOUD_MODE = supabase is not None


def to_png_bytes(image: Image.Image) -> bytes:
    image = ImageOps.exif_transpose(image).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def save_base_photo(image: Image.Image):
    data = to_png_bytes(image)

    if CLOUD_MODE:
        storage = supabase.storage.from_(BUCKET)
        try:
            storage.remove(["profile/base_photo.png"])
        except Exception:
            pass

        storage.upload(
            path="profile/base_photo.png",
            file=data,
            file_options={"content-type": "image/png", "upsert": "true"},
        )
    else:
        LOCAL_BASE.write_bytes(data)


def load_base_photo():
    try:
        if CLOUD_MODE:
            data = supabase.storage.from_(BUCKET).download("profile/base_photo.png")
            return Image.open(io.BytesIO(data)).convert("RGB")

        if LOCAL_BASE.exists():
            return Image.open(LOCAL_BASE).convert("RGB")

    except Exception:
        return None

    return None


def remove_base_photo():
    if CLOUD_MODE:
        try:
            supabase.storage.from_(BUCKET).remove(["profile/base_photo.png"])
        except Exception:
            pass
    else:
        LOCAL_BASE.unlink(missing_ok=True)


def save_garment(image: Image.Image, category: str, original_name: str):
    safe_stem = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in Path(original_name).stem
    )[:40]

    if not safe_stem:
        safe_stem = "item"

    filename = f"{safe_stem}_{uuid.uuid4().hex[:8]}.png"
    data = to_png_bytes(image)

    if CLOUD_MODE:
        path = f"wardrobe/{category}/{filename}"
        supabase.storage.from_(BUCKET).upload(
            path=path,
            file=data,
            file_options={"content-type": "image/png", "upsert": "false"},
        )
        return path

    local_path = LOCAL_ROOT / category / filename
    local_path.write_bytes(data)
    return str(local_path)


def list_garments(category: str):
    items = []

    if CLOUD_MODE:
        try:
            rows = supabase.storage.from_(BUCKET).list(f"wardrobe/{category}")

            for row in rows:
                name = row.get("name")
                if not name or name.startswith("."):
                    continue

                path = f"wardrobe/{category}/{name}"

                try:
                    data = supabase.storage.from_(BUCKET).download(path)
                    image = Image.open(io.BytesIO(data)).convert("RGB")
                    items.append((path, image))
                except Exception:
                    continue
        except Exception:
            pass

    else:
        for path in sorted((LOCAL_ROOT / category).glob("*.png"), reverse=True):
            try:
                items.append((str(path), Image.open(path).convert("RGB")))
            except Exception:
                continue

    return items


def delete_garment(path: str):
    if CLOUD_MODE:
        supabase.storage.from_(BUCKET).remove([path])
    else:
        Path(path).unlink(missing_ok=True)


def load_garment(path: str):
    if not path:
        return None

    try:
        if CLOUD_MODE:
            data = supabase.storage.from_(BUCKET).download(path)
            return Image.open(io.BytesIO(data)).convert("RGB")

        return Image.open(path).convert("RGB")

    except Exception:
        return None


# ============================================================
# AI VIRTUAL TRY-ON
# ============================================================

@st.cache_resource
def get_vton_client():
    token = get_secret("HF_TOKEN")

    if token:
        return Client("yisol/IDM-VTON", token=token)

    return Client("yisol/IDM-VTON")


def extract_output_image(result):
    value = result[0] if isinstance(result, (list, tuple)) else result

    if isinstance(value, str):
        return Image.open(value).convert("RGB")

    if isinstance(value, dict):
        path = value.get("path") or value.get("name")
        if path:
            return Image.open(path).convert("RGB")

    if isinstance(value, list) and value:
        first = value[0]

        if isinstance(first, str):
            return Image.open(first).convert("RGB")

        if isinstance(first, dict):
            path = first.get("path") or first.get("name")
            if path:
                return Image.open(path).convert("RGB")

    raise RuntimeError("The AI returned an unexpected output format.")


def run_tryon(person_image: Image.Image, garment_image: Image.Image, category: str):
    prompts = {
        "tops": "women's upper-body garment, preserve the exact style, color and texture",
        "bottoms": "women's lower-body garment, preserve the exact style, color and texture",
        "dresses": "women's dress, preserve the exact style, color and texture",
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        person_path = Path(temp_dir) / "person.png"
        garment_path = Path(temp_dir) / "garment.png"

        person_image.convert("RGB").save(person_path)
        garment_image.convert("RGB").save(garment_path)

        client = get_vton_client()

        result = client.predict(
            dict={
                "background": handle_file(str(person_path)),
                "layers": [],
                "composite": None,
            },
            garm_img=handle_file(str(garment_path)),
            garment_des=prompts[category],
            is_checked=True,
            is_checked_crop=False,
            denoise_steps=30,
            seed=42,
            api_name="/tryon",
        )

        return extract_output_image(result)


# ============================================================
# SESSION STATE
# ============================================================

for key in [
    "selected_top",
    "selected_bottom",
    "selected_dress",
    "generated_look",
]:
    if key not in st.session_state:
        st.session_state[key] = None


# ============================================================
# HEADER
# ============================================================

st.title("🎀 Her Closet")
st.caption("A cute little digital wardrobe made just for her ✨")

if CLOUD_MODE:
    st.success("☁️ Permanent cloud storage is connected.")
else:
    st.info(
        "Using local storage for now. "
        "You can connect Supabase later so uploaded clothes stay permanently."
    )

# ============================================================
# MAIN AREA
# ============================================================

left, right = st.columns([0.9, 1.1], gap="large")

with left:
    st.subheader("💗 Her photo")

    base_photo = load_base_photo()

    if base_photo is not None:
        st.image(base_photo, use_container_width=True)

        with st.expander("Change her photo"):
            replacement = st.file_uploader(
                "Choose a new full-body photo",
                type=["png", "jpg", "jpeg", "webp"],
                key="replace_base",
            )

            if replacement:
                preview = ImageOps.exif_transpose(
                    Image.open(replacement)
                ).convert("RGB")

                st.image(preview, width=280)

                if st.button(
                    "💗 Use this photo",
                    type="primary",
                    use_container_width=True,
                ):
                    save_base_photo(preview)
                    st.session_state.generated_look = None
                    st.rerun()

            if st.button(
                "🗑️ Remove current photo",
                use_container_width=True,
            ):
                remove_base_photo()
                st.session_state.generated_look = None
                st.rerun()

    else:
        st.markdown(
            '<div class="soft-card">Upload her full-body photo to begin 💕</div>',
            unsafe_allow_html=True,
        )

        first_photo = st.file_uploader(
            "Upload her photo",
            type=["png", "jpg", "jpeg", "webp"],
            key="first_base",
        )

        if first_photo:
            preview = ImageOps.exif_transpose(
                Image.open(first_photo)
            ).convert("RGB")

            st.image(preview, width=300)

            if st.button(
                "💗 Save her photo",
                type="primary",
                use_container_width=True,
            ):
                save_base_photo(preview)
                st.rerun()


with right:
    st.subheader("✨ Today's look")

    display_image = st.session_state.generated_look or base_photo

    if display_image is not None:
        st.image(display_image, use_container_width=True)
    else:
        st.markdown(
            '<div class="soft-card">Her AI outfit will appear here ✨</div>',
            unsafe_allow_html=True,
        )

    selected_labels = []

    if st.session_state.selected_dress:
        selected_labels.append("👗 Dress")
    else:
        if st.session_state.selected_top:
            selected_labels.append("👚 Top")

        if st.session_state.selected_bottom:
            selected_labels.append("👖 Bottom")

    st.caption(
        "Selected: "
        + (", ".join(selected_labels) if selected_labels else "nothing yet")
    )

    c1, c2 = st.columns(2)

    with c1:
        generate_clicked = st.button(
            "✨ Try on selected look",
            type="primary",
            use_container_width=True,
            disabled=(base_photo is None or not selected_labels),
        )

    with c2:
        if st.button(
            "↺ Clear selection",
            use_container_width=True,
        ):
            st.session_state.selected_top = None
            st.session_state.selected_bottom = None
            st.session_state.selected_dress = None
            st.session_state.generated_look = None
            st.rerun()

    if generate_clicked:
        try:
            result = base_photo.copy()

            if st.session_state.selected_dress:
                dress = load_garment(st.session_state.selected_dress)

                if dress is None:
                    raise RuntimeError("Could not load the selected dress.")

                with st.spinner("✨ AI is fitting the dress..."):
                    result = run_tryon(result, dress, "dresses")

            else:
                if st.session_state.selected_top:
                    top = load_garment(st.session_state.selected_top)

                    if top is None:
                        raise RuntimeError("Could not load the selected top.")

                    with st.spinner("👚 AI is fitting the top..."):
                        result = run_tryon(result, top, "tops")

                if st.session_state.selected_bottom:
                    bottom = load_garment(st.session_state.selected_bottom)

                    if bottom is None:
                        raise RuntimeError("Could not load the selected bottom.")

                    with st.spinner("👖 AI is fitting the bottom..."):
                        result = run_tryon(result, bottom, "bottoms")

            st.session_state.generated_look = result
            st.rerun()

        except Exception as exc:
            st.error("The free AI try-on service is busy or unavailable right now.")
            st.caption("Wait a little and try again.")
            st.exception(exc)

    if st.session_state.generated_look is not None:
        output = io.BytesIO()
        st.session_state.generated_look.save(output, "PNG")

        st.download_button(
            "📸 Save this look",
            data=output.getvalue(),
            file_name="her-look.png",
            mime="image/png",
            use_container_width=True,
        )

# ============================================================
# WARDROBE
# ============================================================

st.divider()
st.header("🛍️ Her wardrobe")

tops_tab, bottoms_tab, dresses_tab, add_tab = st.tabs(
    ["👚 Tops", "👖 Bottoms", "👗 Dresses", "＋ Add clothes"]
)


def render_wardrobe(category: str, state_key: str):
    items = list_garments(category)

    if not items:
        st.info("Nothing here yet. Add the first piece in the ＋ Add clothes tab 💕")
        return

    for start in range(0, len(items), 3):
        cols = st.columns(3)

        for col, (path, image) in zip(cols, items[start:start + 3]):
            with col:
                st.image(image, use_container_width=True)

                is_selected = st.session_state[state_key] == path

                if st.button(
                    "✓ Selected" if is_selected else "Wear this",
                    key=f"select_{path}",
                    use_container_width=True,
                ):
                    if category == "dresses":
                        st.session_state.selected_top = None
                        st.session_state.selected_bottom = None
                        st.session_state.selected_dress = path
                    else:
                        st.session_state.selected_dress = None
                        st.session_state[state_key] = path

                    st.session_state.generated_look = None
                    st.rerun()

                if st.button(
                    "🗑️ Delete",
                    key=f"delete_{path}",
                    use_container_width=True,
                ):
                    delete_garment(path)

                    if st.session_state[state_key] == path:
                        st.session_state[state_key] = None

                    st.session_state.generated_look = None
                    st.rerun()


with tops_tab:
    render_wardrobe("tops", "selected_top")

with bottoms_tab:
    render_wardrobe("bottoms", "selected_bottom")

with dresses_tab:
    render_wardrobe("dresses", "selected_dress")

with add_tab:
    st.subheader("Add a new piece 💕")

    add_left, add_right = st.columns(2)

    with add_left:
        new_item = st.file_uploader(
            "Choose a clothing photo",
            type=["png", "jpg", "jpeg", "webp"],
            key="new_garment",
        )

    with add_right:
        add_category = st.selectbox(
            "What is it?",
            options=["tops", "bottoms", "dresses"],
            format_func=lambda value: CATEGORY_LABELS[value],
        )

    if new_item:
        garment_preview = ImageOps.exif_transpose(
            Image.open(new_item)
        ).convert("RGB")

        st.image(garment_preview, width=320)

        st.caption(
            "Best results: use one garment per photo, clearly visible, "
            "laid flat or on a simple background."
        )

        if st.button(
            "＋ Add to her closet",
            type="primary",
            use_container_width=True,
        ):
            save_garment(
                garment_preview,
                add_category,
                new_item.name,
            )

            st.success("Added 💗")
            st.rerun()


st.divider()
st.caption(
    "This version uses AI virtual try-on instead of simple PNG overlays."
)
