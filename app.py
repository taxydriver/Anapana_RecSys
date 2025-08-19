import math, requests, streamlit as st, pandas as pd
import os

# ---------- CONFIG ----------
st.set_page_config(page_title="Anapana Poster Rater (adaptive)", page_icon="🎬", layout="wide")
st.title("🎬 IMDb-style Top Movies (via TMDb) — Adaptive Rater")
st.caption("Click 👍/👎 and the grid will adapt. This simulates a live recommender loop.")


TMDB_API_BASE = "https://api.themoviedb.org/3"
POSTER_BASE   = "https://image.tmdb.org/t/p/w342"
TARGET_COUNT  = 20       # fetch more so we have room to adapt
GRID_CARDS    = 15         # how many posters on screen
COLS_PER_ROW  = 5


TMDB_API_KEY = st.secrets.get("TMDB_API_KEY") or os.getenv("TMDB_API_KEY", "")
if not TMDB_API_KEY:
    st.error("TMDb key missing. Add TMDB_API_KEY to Streamlit Secrets (or env).")
    st.stop()

# ---------- FETCH ----------
@st.cache_data(show_spinner=False)
def fetch_genres(api_key: str):
    r = requests.get(f"{TMDB_API_BASE}/genre/movie/list",
                     params={"api_key": api_key, "language":"en-US"}, timeout=20)
    r.raise_for_status()
    data = r.json().get("genres", [])
    id2name = {g["id"]: g["name"] for g in data}
    return id2name

@st.cache_data(show_spinner=False)
def fetch_top_rated_movies(n: int, api_key: str):
    movies = []
    per_page = 20
    pages = math.ceil(n / per_page)
    for page in range(1, pages + 1):
        r = requests.get(f"{TMDB_API_BASE}/movie/top_rated",
                         params={"api_key": api_key, "language":"en-US", "page": page},
                         timeout=20)
        r.raise_for_status()
        data = r.json()
        for m in data.get("results", []):
            movies.append({
                "tmdb_id": m.get("id"),
                "title": m.get("title") or m.get("original_title"),
                "year": (m.get("release_date") or "")[:4],
                "poster_path": m.get("poster_path"),
                "vote_avg": m.get("vote_average"),
                "genre_ids": m.get("genre_ids", []),
            })
        if len(movies) >= n:
            break
    return movies[:n]

with st.spinner("Fetching TMDb metadata..."):
    GENRES = fetch_genres(TMDB_API_KEY)            # id -> name
    MOVIES = fetch_top_rated_movies(TARGET_COUNT, TMDB_API_KEY)

# ---------- STATE ----------
# persistent taste model over TMDb genres
if "profile" not in st.session_state:
    st.session_state.profile = {gid: 0.0 for gid in GENRES.keys()}
if "seen" not in st.session_state:
    st.session_state.seen = set()  # tmdb_ids rated
if "display_ids" not in st.session_state:
    # initialize with the first GRID_CARDS movies
    st.session_state.display_ids = [m["tmdb_id"] for m in MOVIES[:GRID_CARDS]]
if "votes" not in st.session_state:
    st.session_state.votes = {}  # tmdb_id -> +1/-1

# Quick index for lookup
ID2MOVIE = {m["tmdb_id"]: m for m in MOVIES}

# ---------- SCORING / RECOMMENDER ----------
def genre_vector(movie):
    vec = {gid: 0.0 for gid in GENRES.keys()}
    for gid in movie.get("genre_ids", []):
        if gid in vec: vec[gid] = 1.0
    return vec

def recommend_rank():
    """
    Rank all unseen movies by simple content-based score:
    score = sum(profile[g] * movie_onehot[g])
    (profile is updated by likes/dislikes)
    """
    prof = st.session_state.profile
    ranked = []
    for m in MOVIES:
        if m["tmdb_id"] in st.session_state.seen or m["tmdb_id"] in st.session_state.display_ids:
            continue
        # dot product
        score = 0.0
        for gid in m.get("genre_ids", []):
            score += prof.get(gid, 0.0)
        ranked.append((score, m["tmdb_id"]))
    ranked.sort(reverse=True, key=lambda x: x[0])
    return [mid for _, mid in ranked]

def apply_feedback(tmdb_id: int, like: bool):
    """Update user profile with simple +1/-1 per genre, mark seen, store vote."""
    m = ID2MOVIE[tmdb_id]
    delta = 1.0 if like else -1.0
    for gid in m.get("genre_ids", []):
        st.session_state.profile[gid] = st.session_state.profile.get(gid, 0.0) + delta
    st.session_state.seen.add(tmdb_id)
    st.session_state.votes[tmdb_id] = 1 if like else -1

def replace_card_at_position(pos: int):
    """Pull next best candidate and put it into the given card slot."""
    ranked = recommend_rank()
    if ranked:
        st.session_state.display_ids[pos] = ranked[0]
    else:
        # nothing left; pick a random unseen or keep as-is
        remaining = [m["tmdb_id"] for m in MOVIES
                     if m["tmdb_id"] not in st.session_state.seen and m["tmdb_id"] not in st.session_state.display_ids]
        if remaining:
            st.session_state.display_ids[pos] = remaining[0]

# ---------- UI ----------
# Legend for your learned taste
with st.expander("Your learned taste (by genre)"):
    prof = st.session_state.profile
    # show only non-zero genres
    nz = [(GENRES[g], v) for g, v in prof.items() if abs(v) > 0.0001]
    if not nz:
        st.write("No signals yet. Start liking / disliking!")
    else:
        st.dataframe(pd.DataFrame(sorted(nz, key=lambda x: -x[1]), columns=["Genre","Weight"]))

# Render grid
rows = math.ceil(GRID_CARDS / COLS_PER_ROW)
for r in range(rows):
    cols = st.columns(COLS_PER_ROW)
    for c_idx in range(COLS_PER_ROW):
        pos = r * COLS_PER_ROW + c_idx
        if pos >= len(st.session_state.display_ids): break
        mid = st.session_state.display_ids[pos]
        m = ID2MOVIE[mid]
        with cols[c_idx]:
            poster_url = f"{POSTER_BASE}{m['poster_path']}" if m["poster_path"] else f"https://picsum.photos/seed/{mid}/300/450"
            st.image(poster_url, use_column_width=True)
            st.markdown(f"**{m['title']}** ({m['year']})")
            st.caption(" • ".join(GENRES.get(gid, "?") for gid in m.get("genre_ids", [])) or "No genres")

            b1, b2 = st.columns(2)
            if b1.button("👍 Like", key=f"like_{mid}"):
                apply_feedback(mid, like=True)
                replace_card_at_position(pos)
                st.rerun()
            if b2.button("👎 Dislike", key=f"dis_{mid}"):
                apply_feedback(mid, like=False)
                replace_card_at_position(pos)
                st.rerun()

# Export votes (still useful for later training)
votes_df = pd.DataFrame([
    {"tmdb_id": mid, "title": ID2MOVIE[mid]["title"], "vote": v}
    for mid, v in st.session_state.votes.items()
])
st.download_button("Download my feedback (CSV)",
                   votes_df.to_csv(index=False).encode("utf-8"),
                   "feedback.csv", "text/csv")

st.markdown(
    "<div style='text-align:center; font-size:12px; opacity:0.7;'>"
    "This product uses the TMDb API but is not endorsed or certified by TMDb."
    "</div>",
    unsafe_allow_html=True,
)