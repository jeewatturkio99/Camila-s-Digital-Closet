import io
import uuid
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps
from rembg import remove, new_session

st.set_page_config(page_title="My Digital Closet", page_icon="👗", layout="wide")

BASE_PHOTO_PATH = Path("base_photo.png")
CLOSET_ROOT = Path("closet")
CATEGORY_FOLDERS = {
    "Shirt": CLOSET_ROOT / "shirts",
    "Pants": CLOSET_ROOT / "pants",
    "Shoes": CLOSET_ROOT / "shoes",
}

for folder in CATEGORY_FOLDERS.values():
    folder.mkdir(parents=True, exist_ok=True)

for key in ("selected_shirt", "selected_pants", "selected_shoes"):
    if key not in st.session_state:
        st.session_state[key] = None

@st.cache_resource
def load_rembg_session():
    return new_session("u2net")

def get_clothing_files(folder):
    return sorted(folder.glob("*.png"))

def trim_transparency(image):
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    return image.crop(bbox) if bbox else image

def resize_to_fit(image, max_width, max_height):
    image = image.copy()
    image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return image

def add_layer(canvas, path, category, x_offset=0, y_offset=0, scale=100):
    if not path:
        return canvas

    try:
        item = trim_transparency(Image.open(path).convert("RGBA"))
    except Exception:
        return canvas

    w, h = canvas.size
    settings = {
        "Shirt": (0.55, 0.43, 0.50, 0.36),
        "Pants": (0.48, 0.52, 0.50, 0.63),
        "Shoes": (0.55, 0.20, 0.50, 0.91),
    }
    width_ratio, height_ratio, cx_ratio, cy_ratio = settings[category]

    item = resize_to_fit(item, int(w * width_ratio), int(h * height_ratio))
    factor = scale / 100
    item = item.resize(
        (max(1, int(item.width * factor)), max(1, int(item.height * factor))),
        Image.Resampling.LANCZOS,
    )

    x = int(w * cx_ratio + x_offset - item.width / 2)
    y = int(h * cy_ratio + y_offset - item.height / 2)
    canvas.alpha_composite(item, (x, y))
    return canvas

def create_outfit(base, adjustments):
    canvas = base.convert("RGBA").copy()
    canvas = add_layer(
        canvas, st.session_state.selected_pants, "Pants",
        adjustments["pants_x"], adjustments["pants_y"], adjustments["pants_scale"]
    )
    canvas = add_layer(
        canvas, st.session_state.selected_shirt, "Shirt",
        adjustments["shirt_x"], adjustments["shirt_y"], adjustments["shirt_scale"]
    )
    canvas = add_layer(
        canvas, st.session_state.selected_shoes, "Shoes",
        adjustments["shoes_x"], adjustments["shoes_y"], adjustments["shoes_scale"]
    )
    return canvas

def process_upload(uploaded_file, category):
    image = ImageOps.exif_transpose(Image.open(uploaded_file)).convert("RGBA")
    output = remove(image, session=load_rembg_session())

    if not isinstance(output, Image.Image):
        output = Image.open(io.BytesIO(output)).convert("RGBA")

    output = trim_transparency(output)
    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in Path(uploaded_file.name).stem
    )
    destination = CATEGORY_FOLDERS[category] / f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    output.save(destination, "PNG")
    return destination, output

def gallery(category):
    files = get_clothing_files(CATEGORY_FOLDERS[category])
    if not files:
        st.info(f"No {category.lower()} items yet.")
        return

    state_key = {
        "Shirt": "selected_shirt",
        "Pants": "selected_pants",
        "Shoes": "selected_shoes",
    }[category]

    for start in range(0, len(files), 3):
        cols = st.columns(3)
        for col, path in zip(cols, files[start:start + 3]):
            with col:
                st.image(Image.open(path), use_container_width=True)
                if st.button("Select", key=f"{category}_{path}", use_container_width=True):
                    st.session_state[state_key] = str(path)
                    st.rerun()

st.title("👗 My Digital Closet")
st.caption("Mix and match today's outfit ✨")

left, right = st.columns([1, 1], gap="large")

with left:
    st.header("✨ Today's Look")

    if BASE_PHOTO_PATH.exists():
        base = ImageOps.exif_transpose(Image.open(BASE_PHOTO_PATH)).convert("RGBA")

        with st.expander("⚙️ Adjust clothing fit"):
            shirt_scale = st.slider("Shirt size", 50, 160, 100)
            shirt_x = st.slider("Shirt left / right", -300, 300, 0)
            shirt_y = st.slider("Shirt up / down", -300, 300, 0)

            pants_scale = st.slider("Pants size", 50, 160, 100)
            pants_x = st.slider("Pants left / right", -300, 300, 0)
            pants_y = st.slider("Pants up / down", -300, 300, 0)

            shoes_scale = st.slider("Shoes size", 50, 180, 100)
            shoes_x = st.slider("Shoes left / right", -300, 300, 0)
            shoes_y = st.slider("Shoes up / down", -300, 300, 0)

        adjustments = {
            "shirt_scale": shirt_scale, "shirt_x": shirt_x, "shirt_y": shirt_y,
            "pants_scale": pants_scale, "pants_x": pants_x, "pants_y": pants_y,
            "shoes_scale": shoes_scale, "shoes_x": shoes_x, "shoes_y": shoes_y,
        }

        outfit = create_outfit(base, adjustments)
        st.image(outfit, use_container_width=True)

        buffer = io.BytesIO()
        outfit.save(buffer, "PNG")
        st.download_button(
            "📸 Save Today's Outfit",
            buffer.getvalue(),
            "todays_outfit.png",
            "image/png",
            use_container_width=True,
        )
    else:
        st.warning("Upload a file named base_photo.png to your GitHub repository.")

    if st.button("🧹 Clear Outfit", use_container_width=True):
        st.session_state.selected_shirt = None
        st.session_state.selected_pants = None
        st.session_state.selected_shoes = None
        st.rerun()

with right:
    st.header("👚 Digital Closet")
    shirt_tab, pants_tab, shoes_tab = st.tabs(["👕 Shirts", "👖 Pants", "👟 Shoes"])

    with shirt_tab:
        gallery("Shirt")
    with pants_tab:
        gallery("Pants")
    with shoes_tab:
        gallery("Shoes")

st.divider()
st.header("➕ Add Something to the Closet")

upload_col, category_col = st.columns(2)
with upload_col:
    uploaded = st.file_uploader("Upload clothing photo", type=["png", "jpg", "jpeg", "webp"])
with category_col:
    category = st.selectbox("Category", ["Shirt", "Pants", "Shoes"])

if uploaded:
    st.image(uploaded, caption="Original photo", width=300)

    if st.button("✨ Remove Background & Add to Closet", type="primary"):
        with st.spinner("Removing background..."):
            try:
                path, processed = process_upload(uploaded, category)
                st.success(f"Added to {category} closet!")
                st.image(processed, caption="Background removed", width=300)

                state_key = {
                    "Shirt": "selected_shirt",
                    "Pants": "selected_pants",
                    "Shoes": "selected_shoes",
                }[category]
                st.session_state[state_key] = str(path)
            except Exception as exc:
                st.error("Background removal failed.")
                st.exception(exc)

st.caption("Made with ❤️ using Streamlit, Pillow and rembg.")
