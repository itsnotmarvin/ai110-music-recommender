"""Threadline — an explorable, source-backed music story prototype."""

from __future__ import annotations

import html
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote_plus

import streamlit as st
import streamlit.components.v1 as components

from src.archive import ArchiveRepository
from src.apple_music import (
    RECOMMENDATION_MODES,
    AppleMusicImportError,
    AppleMusicExport,
    analyze_library,
    parse_apple_music_export,
    recommend_from_library,
)
from src.demo_data import DemoSimilarityClient, demo_apple_music_export
from src.artist_catalog import MusicBrainzCatalogClient
from src.live_events import TicketmasterEventsClient
from src.lyrics import LrcLibClient
from src.qa import GroundedAnswerEngine
from src.song_context import build_song_context
from src.playlist_recommender import (
    HybridPlaylistRecommender,
    LastfmClient,
    PlaylistRecommendationError,
)


ROOT = Path(__file__).resolve().parent
ARCHIVE_PATH = ROOT / "data" / "archive.json"
TYLER_JOURNEY_PATH = ROOT / "data" / "tyler_journey.json"
SONG_CONTEXT_PATH = ROOT / "data" / "song_contexts.json"
REPOSITORY_DATA_PATHS = tuple(
    ROOT / "data" / filename
    for filename in (
        "archive.json",
        "odd_future_members.json",
        "track_catalog.json",
        "story_profiles.json",
        "interview_videos.json",
        "song_contexts.json",
    )
)

ODD_FUTURE_COMMONS_PHOTOS = {
    "brandun-deshay": ("https://upload.wikimedia.org/wikipedia/commons/2/27/Deshaymephi.jpg", "https://commons.wikimedia.org/wiki/File:Deshaymephi.jpg", "Yleonmgnt · CC BY 3.0"),
    "casey-veggies": ("https://upload.wikimedia.org/wikipedia/commons/a/a6/Casey_Veggies_August_2012.jpg", "https://commons.wikimedia.org/wiki/File:Casey_Veggies_August_2012.jpg", "Dj Teck 16 · CC BY 2.0"),
    "domo-genesis": ("https://upload.wikimedia.org/wikipedia/commons/9/9a/Domo_Genesis_Toronto_2011.png", "https://commons.wikimedia.org/wiki/File:Domo_Genesis_Toronto_2011.png", "thecomeupshow · CC BY 2.0"),
    "earl-sweatshirt": ("https://upload.wikimedia.org/wikipedia/commons/7/79/Earl_Sweatshirt_Day_N_Night_Festival.png", "https://commons.wikimedia.org/wiki/File:Earl_Sweatshirt_Day_N_Night_Festival.png", "Frank Morales · CC BY-SA 4.0"),
    "frank-ocean": ("https://upload.wikimedia.org/wikipedia/commons/e/e3/Frank_Ocean_2022_Blonded.jpg", "https://commons.wikimedia.org/wiki/File:Frank_Ocean_2022_Blonded.jpg", "Andras Ladocsi · CC BY-SA 4.0"),
    "hodgy": ("https://upload.wikimedia.org/wikipedia/commons/9/93/2011-07-03-eurockeennes-17.jpg", "https://commons.wikimedia.org/wiki/File:2011-07-03-eurockeennes-17.jpg", "Thomas Bresson · CC BY 3.0"),
    "jasper-dolphin": ("https://upload.wikimedia.org/wikipedia/commons/d/d3/Jasper_Dolphin_%28cropped%29.jpg", "https://commons.wikimedia.org/wiki/File:Jasper_Dolphin_(cropped).jpg", "Mileslwayne · CC BY 4.0"),
    "left-brain": ("https://upload.wikimedia.org/wikipedia/commons/0/0b/Left_Brain_live.jpg", "https://commons.wikimedia.org/wiki/File:Left_Brain_live.jpg", "IrishLad1916 · CC BY-SA 3.0"),
    "matt-martians": ("https://upload.wikimedia.org/wikipedia/commons/1/10/Matt_Keys_In_Boston.jpeg", "https://commons.wikimedia.org/wiki/File:Matt_Keys_In_Boston.jpeg", "Ilovejb1 · CC BY-SA 3.0"),
    "mike-g": ("https://upload.wikimedia.org/wikipedia/commons/7/71/2011-07-03-eurockeennes-3.jpg", "https://commons.wikimedia.org/wiki/File:2011-07-03-eurockeennes-3.jpg", "Thomas Bresson · CC BY 3.0"),
    "na-kel-smith": ("https://upload.wikimedia.org/wikipedia/commons/5/58/Na-Kel_Smith_in_2018.jpg", "https://commons.wikimedia.org/wiki/File:Na-Kel_Smith_in_2018.jpg", "ColliderVideo · CC BY 3.0"),
    "syd": ("https://upload.wikimedia.org/wikipedia/commons/1/1d/Syd_tha_Kid_Toronto_2011.jpg", "https://commons.wikimedia.org/wiki/File:Syd_tha_Kid_Toronto_2011.jpg", "thecomeupshow · CC BY 2.0"),
    "the-internet": ("https://upload.wikimedia.org/wikipedia/commons/c/c3/The_Internet.jpg", "https://commons.wikimedia.org/wiki/File:The_Internet.jpg", "Incase · CC BY 2.0"),
}


st.set_page_config(
    page_title="Threadline — stories behind the music",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def load_repository(data_revision: tuple[int, ...]) -> ArchiveRepository:
    """Load the archive, invalidating when any hydrated data file changes."""
    del data_revision
    return ArchiveRepository.from_json(ARCHIVE_PATH)


@st.cache_data(show_spinner=False)
def load_tyler_journey(data_revision: int) -> dict:
    """Load Tyler's isolated guided path without changing shared artist stories."""
    del data_revision
    return json.loads(TYLER_JOURNEY_PATH.read_text(encoding="utf-8"))


@st.cache_data(ttl=3600, show_spinner=False)
def search_catalog(query: str) -> dict:
    response = MusicBrainzCatalogClient().search_artists(query)
    return {
        "status": response.status,
        "message": response.message,
        "artists": [artist.to_dict() for artist in response.artists],
    }


@st.cache_data(ttl=86400, show_spinner=False)
def load_catalog_profile(artist: dict) -> dict:
    return MusicBrainzCatalogClient().load_profile(artist)


@st.cache_data(ttl=900, show_spinner=False)
def load_live_events(artist: str, city: str, api_configured: bool) -> dict:
    result = TicketmasterEventsClient().search(artist, city)
    return {
        "status": result.status,
        "events": result.events,
        "checked_at": result.checked_at,
        "provider": result.provider,
        "message": result.message,
    }


@st.cache_data(ttl=86400, show_spinner=False)
def load_lrclib_lyrics(track: str, artist: str, album: str) -> dict:
    """Fetch lyrics on demand without writing them into the static archive."""
    return LrcLibClient().search(track, artist, album).to_dict()


@st.cache_data(show_spinner=False)
def load_song_contexts(data_revision: int) -> dict:
    """Load the reviewed song-context layer independently from live lyrics."""
    del data_revision
    return json.loads(SONG_CONTEXT_PATH.read_text(encoding="utf-8"))


def safe(value: object) -> str:
    return html.escape(str(value))


def refresh_song_record(repository: ArchiveRepository, selected: dict) -> dict:
    """Resolve a session song against the latest reviewed archive revision."""
    artist_name = str(selected.get("artist", "")).casefold()
    album_title = str(selected.get("album", "")).casefold()
    song_title = str(selected.get("title", "")).casefold()
    for universe in repository.data.get("universes", []):
        if universe.get("name", "").casefold() != artist_name:
            continue
        for album in universe.get("albums", []):
            if album.get("title", "").casefold() != album_title:
                continue
            for archived_track in album.get("tracks", []):
                if archived_track.get("title", "").casefold() == song_title:
                    return {
                        **selected,
                        **archived_track,
                        "artist": universe["name"],
                        "album": album["title"],
                        "album_year": album["year"],
                        "album_sources": album.get("source_ids", []),
                    }
    return selected


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink: #f3efe6;
          --muted: #aaa69e;
          --panel: #171716;
          --line: rgba(255,255,255,.10);
          --acid: #d9ff55;
        }
        .stApp { background: #0c0c0b; color: var(--ink); }
        [data-testid="stSidebar"] { background: #121211; border-right: 1px solid var(--line); }
        [data-testid="stSidebar"] > div { padding-top: 1.4rem; }
        .block-container { max-width: 1180px; padding-top: 2rem; padding-bottom: 5rem; }
        h1, h2, h3 { letter-spacing: -.035em; }
        p, li { line-height: 1.62; }
        .brand { font-size: 1.25rem; font-weight: 900; letter-spacing: .12em; }
        .brand-dot { color: var(--acid); }
        .brand-sub { color: var(--muted); font-size: .76rem; margin: .25rem 0 1.5rem; }
        div[data-testid="stLayoutWrapper"]:has(> .st-key-threadline_topbar) {
          position: sticky; top: 0; z-index: 999;
          background: rgba(12,12,11,.96); backdrop-filter: blur(16px);
        }
        .st-key-threadline_topbar {
          border-bottom: 1px solid var(--line); padding: .55rem .1rem .75rem; margin-bottom: .4rem;
        }
        .st-key-threadline_topbar [data-testid="stHorizontalBlock"] { align-items: center; }
        .topbar-brand-block .brand-sub { margin: .2rem 0 0; letter-spacing: .08em; }
        .topbar-description { color: var(--muted); font-size: .76rem; line-height: 1.45; max-width: 430px; }
        .st-key-threadline_topbar div.stButton > button { min-height: 2.55rem; white-space: nowrap; }
        .eyebrow { font-size: .71rem; font-weight: 800; letter-spacing: .15em; text-transform: uppercase; opacity: .76; }
        .home-hero { padding: 5.5rem 0 2rem; max-width: 980px; }
        .home-hero h1 { font-size: clamp(3.5rem, 9vw, 7.7rem); line-height: .87; margin: .8rem 0 1.4rem; letter-spacing: -.07em; }
        .home-hero h1 em { color: var(--acid); font-style: normal; }
        .home-hero p { color: #c1bdb4; font-size: 1.13rem; max-width: 680px; }
        .search-frame { background: #171716; border: 1px solid rgba(217,255,85,.28); border-radius: 24px; padding: 1rem 1.15rem .4rem; box-shadow: 0 22px 90px rgba(0,0,0,.35); }
        .st-key-featured_tyler_story {
          margin: 2.1rem 0 .5rem; padding: 1rem;
          border: 1px solid rgba(217,255,85,.22); border-radius: 26px;
          background: linear-gradient(135deg, #1a1a18 0%, #11110f 72%);
          box-shadow: 0 24px 80px rgba(0,0,0,.28);
        }
        .featured-story-photo { margin: 0; }
        .featured-story-photo img {
          display: block; width: 100%; height: 290px; object-fit: cover;
          object-position: center 22%; border-radius: 18px;
        }
        .featured-story-photo figcaption {
          color: #77736c; font-size: .66rem; margin: .45rem .15rem 0;
        }
        .featured-story-photo a { color: #918d85 !important; }
        .featured-story-copy { padding: .3rem .25rem; }
        .featured-story-copy h2 { font-size: clamp(2rem, 4vw, 3.25rem); line-height: .98; margin: .45rem 0 .9rem; }
        .featured-story-copy p { color: #bcb8af; margin-bottom: .8rem; }
        .featured-story-copy strong { color: var(--ink); }
        .st-key-featured_tyler_link div.stButton > button,
        .st-key-featured_tyler_link div.stButton > button:hover,
        .st-key-featured_tyler_link div.stButton > button p {
          color: #0c0c0b !important;
        }
        .journey-hero {
          display: grid; grid-template-columns: minmax(0,1.4fr) minmax(260px,.65fr);
          gap: 2rem; align-items: stretch; margin: 2rem 0 1.25rem;
        }
        .journey-hero-copy {
          min-height: 390px; padding: 2.25rem; border-radius: 28px;
          border: 1px solid rgba(217,255,85,.22);
          background: radial-gradient(circle at 92% 10%, rgba(217,255,85,.12), transparent 34%), #151514;
          display: flex; flex-direction: column; justify-content: flex-end;
        }
        .journey-hero-copy h1 {
          font-size: clamp(3.4rem, 8vw, 6.9rem); line-height: .84;
          letter-spacing: -.075em; margin: .65rem 0 1rem;
        }
        .journey-hero-copy h2 { color: var(--acid); font-size: clamp(1.35rem,3vw,2.15rem); margin: 0 0 .8rem; }
        .journey-hero-copy p { color: #c5c1b8; max-width: 650px; margin: 0; }
        .journey-portrait { position: relative; overflow: hidden; min-height: 390px; margin: 0; border-radius: 28px; border: 1px solid var(--line); }
        .journey-portrait img { width: 100%; height: 100%; object-fit: cover; object-position: center 22%; display: block; }
        .journey-portrait figcaption { position: absolute; inset: auto 0 0; padding: 2.6rem .9rem .8rem; color: #dedad1; font-size: .64rem; background: linear-gradient(transparent,rgba(0,0,0,.9)); }
        .journey-portrait a { color: #fff !important; }
        .journey-progress-copy { display: flex; justify-content: space-between; color: var(--muted); font-size: .76rem; margin: 0 0 .4rem; }
        .journey-progress-track { height: 8px; border-radius: 999px; overflow: hidden; background: #262624; margin-bottom: 1rem; }
        .journey-progress-fill { height: 100%; border-radius: inherit; background: var(--acid); }
        .chapter-context { border-top: 1px solid var(--line); padding: 1.25rem .15rem .4rem; }
        .chapter-context h3 { font-size: 1.35rem; margin: .25rem 0 .6rem; }
        .chapter-context p { color: #c4c0b8; }
        .essential-card { min-height: 245px; border: 1px solid var(--line); border-radius: 22px; padding: 1.25rem; background: linear-gradient(155deg,#1a1a18,#11110f); }
        .essential-number { color: var(--acid); font-size: .68rem; letter-spacing: .12em; font-weight: 800; }
        .essential-card h3 { font-size: 1.45rem; margin: .55rem 0 .7rem; }
        .essential-card p { color: #bdb9b0; font-size: .9rem; }
        .essential-theme { color: #858179; font-size: .7rem; text-transform: uppercase; letter-spacing: .08em; }
        .transition-card { margin: 2.5rem 0 1rem; padding: 1.6rem; border-radius: 22px; background: #181b13; border: 1px solid rgba(217,255,85,.24); }
        .transition-card h3 { margin: .35rem 0 .55rem; }
        .transition-card p { color: #c8c4bc; margin: 0; }
        .st-key-journey_next div.stButton > button,
        .st-key-journey_next div.stButton > button:hover,
        .st-key-journey_next div.stButton > button p { color: #0c0c0b !important; }
        .artist-photo-grid {
          display: grid; grid-template-columns: 1.3fr .85fr;
          grid-template-rows: repeat(2, 205px); gap: .85rem; margin: 1.2rem 0 2.2rem;
        }
        .artist-photo {
          position: relative; overflow: hidden; margin: 0;
          border: 1px solid var(--line); border-radius: 20px; background: #171716;
        }
        .artist-photo:first-child { grid-row: 1 / span 2; }
        .artist-photo img {
          display: block; width: 100%; height: 100%; object-fit: cover;
          transition: transform .35s ease;
        }
        .artist-photo:first-child img { object-position: center 28%; }
        .artist-photo:hover img { transform: scale(1.025); }
        .artist-photo figcaption {
          position: absolute; inset: auto 0 0; padding: 2.4rem .8rem .7rem;
          color: #e2ded5; font-size: .66rem;
          background: linear-gradient(transparent, rgba(0,0,0,.86));
        }
        .artist-photo figcaption a { color: #f3efe6 !important; }
        .result-card { min-height: 165px; background: linear-gradient(150deg, #1b1b19, #111110); border: 1px solid var(--line); border-radius: 20px; padding: 1.2rem; margin-bottom: .55rem; }
        .result-card h3 { font-size: 1.45rem; margin: .35rem 0 .5rem; }
        .result-card p { color: var(--muted); font-size: .86rem; min-height: 2.6rem; }
        .reviewed-badge { color: var(--acid); font-size: .68rem; letter-spacing: .11em; font-weight: 800; }
        .catalog-badge { color: #8ecae6; font-size: .68rem; letter-spacing: .11em; font-weight: 800; }
        .principle-card { min-height: 150px; background: transparent; border-top: 1px solid var(--line); padding: 1.1rem .2rem; }
        .principle-card strong { font-size: 1.1rem; }
        .principle-card p { color: var(--muted); font-size: .86rem; }
        .library-card { background: linear-gradient(150deg, #1b1b19, #111110); border: 1px solid rgba(217,255,85,.18); border-radius: 22px; padding: 1.3rem; margin: .75rem 0; }
        .library-card h3 { font-size: 1.7rem; margin: .35rem 0 .2rem; }
        .library-card p { color: var(--muted); margin: 0 0 .75rem; }
        .score-pill { display:inline-block; color:var(--acid); border:1px solid rgba(217,255,85,.3); border-radius:99px; padding:.25rem .58rem; font-size:.72rem; font-weight:800; }
        .hero {
          position: relative; overflow: hidden; min-height: 300px; padding: 2.1rem;
          border-radius: 28px; border: 1px solid rgba(255,255,255,.15);
          display: flex; flex-direction: column; justify-content: flex-end;
          box-shadow: inset 0 -120px 120px rgba(0,0,0,.35);
        }
        .hero:after {
          content: ""; position: absolute; width: 260px; height: 260px; border-radius: 50%;
          right: -60px; top: -70px; border: 52px solid rgba(255,255,255,.12); transform: rotate(-20deg);
        }
        .hero h1 { position: relative; z-index: 1; font-size: clamp(2.8rem, 7vw, 6.4rem); line-height: .88; margin: .7rem 0 1rem; max-width: 900px; }
        .hero p { position: relative; z-index: 1; max-width: 690px; font-size: 1.06rem; margin: 0; }
        .hero .eyebrow { position: relative; z-index: 1; }
        .meta-row { display: flex; flex-wrap: wrap; gap: .55rem; margin-top: 1rem; }
        .chip { display: inline-block; padding: .34rem .7rem; border-radius: 99px; border: 1px solid var(--line); color: #d8d4cc; font-size: .76rem; background: rgba(255,255,255,.035); }
        .section-label { color: var(--acid); font-size: .73rem; letter-spacing: .14em; text-transform: uppercase; font-weight: 800; margin: 2.8rem 0 .35rem; }
        .section-title { font-size: clamp(1.9rem, 4vw, 3rem); margin: 0 0 .65rem; }
        .lede { color: var(--muted); max-width: 760px; }
        .metric-card, .story-card, .source-card, .guardrail, .empty-note {
          background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 1.1rem 1.2rem;
        }
        .metric-card strong { display: block; font-size: 1.55rem; margin-bottom: .2rem; }
        .metric-card span { color: var(--muted); font-size: .78rem; }
        .cover {
          aspect-ratio: 1/1; border-radius: 16px; padding: 1rem; display: flex;
          align-items: flex-end; font-size: 1.4rem; font-weight: 900; letter-spacing: -.04em;
          border: 1px solid rgba(255,255,255,.15); box-shadow: inset 0 -60px 80px rgba(0,0,0,.35);
        }
        .album-title { font-weight: 800; font-size: 1.05rem; margin-top: .65rem; }
        .album-meta { color: var(--muted); font-size: .79rem; }
        .timeline { border-left: 1px solid rgba(217,255,85,.38); padding-left: 1.35rem; margin-left: .35rem; }
        .story-card { margin: 0 0 1rem; position: relative; }
        .story-card:before { content: ""; position: absolute; width: 9px; height: 9px; border-radius: 50%; background: var(--acid); left: -1.68rem; top: 1.42rem; }
        .story-era { color: var(--acid); font-size: .72rem; font-weight: 800; letter-spacing: .09em; }
        .story-card h3 { margin: .35rem 0 .45rem; }
        .story-card p { color: #c8c4bc; margin-bottom: .35rem; }
        .claim { font-size: .68rem; text-transform: uppercase; letter-spacing: .09em; color: var(--muted); }
        .track { display: grid; grid-template-columns: 34px 1fr minmax(130px, .45fr); gap: .6rem; padding: .82rem .3rem; border-bottom: 1px solid var(--line); align-items: center; }
        .track-num { color: #7d7a74; }
        .track-theme { color: var(--muted); font-size: .78rem; text-align: right; }
        .connection-line { color: var(--muted); min-height: 2.7rem; }
        .answer { font-size: 1.08rem; background: #181b13; border: 1px solid rgba(217,255,85,.22); padding: 1.35rem; border-radius: 18px; }
        .guardrail { border-color: rgba(255,196,96,.38); background: #201b12; color: #f2d6a2; }
        .source-card { margin: .55rem 0; }
        .source-card a { color: var(--acid) !important; text-decoration: none; font-weight: 700; }
        .source-meta { color: var(--muted); font-size: .74rem; }
        .status-live { color: #9ee493; font-weight: 800; }
        .status-static { color: #e6ca76; font-weight: 800; }
        .archive-note { border-left: 3px solid var(--acid); padding-left: 1rem; color: #c9c5bc; }
        .song-context-lead {
          margin: 1rem 0 .85rem; padding: 1.45rem 1.55rem; border-radius: 22px;
          border: 1px solid rgba(217,255,85,.25);
          background: radial-gradient(circle at 92% 8%,rgba(217,255,85,.1),transparent 35%),#151613;
        }
        .song-context-lead h3 { font-size: clamp(1.55rem,3vw,2.25rem); margin: .4rem 0 .7rem; }
        .song-context-lead p { color: #d0ccc3; margin: 0 0 .75rem; }
        .context-timing { color: var(--muted); font-size: .74rem; }
        .context-boundary {
          color: #e9d4aa; background: #201b12; border-left: 3px solid #e6b85c;
          border-radius: 4px 14px 14px 4px; padding: .8rem 1rem; margin: .7rem 0 1.2rem;
        }
        .song-voice-card, .nearby-release-card {
          min-height: 190px; padding: 1.05rem 1.1rem; margin-bottom: .75rem;
          background: #171716; border: 1px solid var(--line); border-radius: 18px;
        }
        .song-voice-card h3, .nearby-release-card h3 { font-size: 1.2rem; margin: .35rem 0 .55rem; }
        .song-voice-card p, .nearby-release-card p { color: #bdb9b0; font-size: .84rem; margin: 0; }
        .nearby-release-card { min-height: 145px; }
        .context-badge { color: var(--acid); font-size: .66rem; font-weight: 800; letter-spacing: .11em; text-transform: uppercase; }
        div.stButton > button { border-radius: 99px; border-color: rgba(255,255,255,.17); }
        div.stButton > button:hover { border-color: var(--acid); color: var(--acid); }
        .st-key-apple_music_cta div.stButton > button,
        .st-key-apple_music_cta div.stButton > button:hover,
        .st-key-apple_music_cta div.stButton > button p {
          color: #0c0c0b !important;
        }
        [data-testid="stForm"] { border-color: var(--line); border-radius: 20px; background: #131312; }
        @media(max-width:640px) {
          .topbar-description { display: none; }
          .st-key-threadline_topbar div.stButton > button { padding-left: .65rem; padding-right: .65rem; }
          .featured-story-photo img { height: 230px; }
          .artist-photo-grid { display: block; }
          .artist-photo { height: 230px; margin-bottom: .75rem; }
          .journey-hero { display: block; }
          .journey-hero-copy { min-height: 355px; padding: 1.35rem; }
          .journey-portrait { min-height: 300px; margin-top: .8rem; }
          .essential-card { min-height: auto; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_top_bar() -> None:
    with st.container(key="threadline_topbar"):
        brand_column, note_column, back_column, home_column, library_column = st.columns(
            [2.05, 3.15, 1.55, 1.1, 1.4],
            vertical_alignment="center",
        )
        brand_column.markdown(
            '<div class="topbar-brand-block">'
            '<div class="brand">THREAD<span class="brand-dot">LINE</span></div>'
            '<div class="brand-sub">THE STORIES BEHIND THE MUSIC</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        note_column.markdown(
            '<div class="topbar-description">Search is the front door. Reviewed stories are an added depth, not a fixed list of choices.</div>',
            unsafe_allow_html=True,
        )
        if st.session_state.get("page") in {"album", "song"}:
            returning_to_journey = bool(st.session_state.get("journey_return"))
            if back_column.button(
                "← Back to chapter" if returning_to_journey else "← Back to artist",
                key="topbar_back_to_artist",
                use_container_width=True,
            ):
                if returning_to_journey:
                    st.session_state.page = "journey"
                else:
                    st.session_state.page = "universe"
                    st.session_state.view = "Albums"
                st.rerun()
        if home_column.button("⌂ Home", key="topbar_home", use_container_width=True):
            st.session_state.page = "home"
            st.session_state.pop("journey_return", None)
            st.session_state.pop("journey_guided_song", None)
            st.rerun()
        if library_column.button(
            "♫ My library",
            key="topbar_library",
            use_container_width=True,
        ):
            st.session_state.page = "library"
            st.session_state.pop("journey_return", None)
            st.session_state.pop("journey_guided_song", None)
            st.rerun()


def open_local_universe(universe_id: str) -> None:
    st.session_state.universe_id = universe_id
    st.session_state.pop("catalog_profile", None)
    st.session_state.pop("selected_album_id", None)
    st.session_state.pop("journey_return", None)
    st.session_state.pop("journey_guided_song", None)
    if universe_id == "tyler-the-creator":
        st.session_state.page = "journey"
        st.session_state.journey_release_index = 0
        st.session_state.journey_track_index = 0
    else:
        st.session_state.page = "universe"
        st.session_state.view = "Overview"


def open_catalog_universe(artist: dict) -> None:
    with st.spinner(f"Opening {artist['name']}…"):
        st.session_state.catalog_profile = load_catalog_profile(artist)
    st.session_state.page = "universe"
    st.session_state.pop("selected_album_id", None)
    st.session_state.pop("journey_return", None)
    st.session_state.pop("journey_guided_song", None)
    st.session_state.view = "Overview"


def open_artist_by_name(repository: ArchiveRepository, artist_name: str) -> None:
    local = repository.find_universes(artist_name, limit=3)
    exact = next(
        (item for item in local if item["name"].casefold() == artist_name.casefold()),
        None,
    )
    if exact:
        open_local_universe(exact["id"])
        return
    response = search_catalog(artist_name)
    if response["artists"]:
        external_exact = next(
            (
                item
                for item in response["artists"]
                if item["name"].casefold() == artist_name.casefold()
            ),
            response["artists"][0],
        )
        open_catalog_universe(external_exact)
        return
    st.session_state.navigation_error = (
        f"The artist catalog could not resolve {artist_name}. Try searching from Home."
    )


def render_featured_story() -> None:
    """Offer a concrete reviewed story to visitors who have not searched yet."""
    with st.container(key="featured_tyler_story"):
        image_column, story_column = st.columns(
            [1.05, 1.45],
            gap="large",
            vertical_alignment="center",
        )
        image_column.markdown(
            """
            <figure class="featured-story-photo">
              <img
                src="https://upload.wikimedia.org/wikipedia/commons/thumb/f/fa/Tyler_the_Creator_2022_cropped.png/960px-Tyler_the_Creator_2022_cropped.png"
                alt="Tyler, the Creator performing onstage in 2022"
              >
              <figcaption>
                Photo: <a href="https://commons.wikimedia.org/wiki/File:Tyler_the_Creator_2022_cropped.png" target="_blank" rel="noopener noreferrer">Raph_PH / Wikimedia Commons</a> · CC BY 2.0
              </figcaption>
            </figure>
            """,
            unsafe_allow_html=True,
        )
        with story_column:
            st.markdown(
                """
                <div class="featured-story-copy">
                  <div class="reviewed-badge">SUGGESTED · REVIEWED STORY</div>
                  <h2>Learn Tyler, the Creator’s story from the beginning.</h2>
                  <p>Start with <strong>Bastard</strong>, then follow the albums, collaborators,
                  public statements, and creative turns that connect his discography.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "Follow the story →",
                key="featured_tyler_link",
                type="primary",
                use_container_width=True,
            ):
                open_local_universe("tyler-the-creator")
                st.rerun()


def tyler_journey_context(repository: ArchiveRepository) -> tuple[dict, dict, dict, dict, int]:
    """Resolve the current release in Tyler's guided story."""
    journey_revision = TYLER_JOURNEY_PATH.stat().st_mtime_ns
    journey = load_tyler_journey(journey_revision)
    universe = repository.get_universe(journey["artist_id"])
    release_index = int(st.session_state.get("journey_release_index", 0))
    release_index = max(0, min(release_index, len(journey["releases"]) - 1))
    st.session_state.journey_release_index = release_index
    chapter = journey["releases"][release_index]
    album = next(
        item for item in universe["albums"] if item["id"] == chapter["album_id"]
    )
    return journey, universe, chapter, album, release_index


def open_journey_track(
    universe: dict,
    album: dict,
    chapter: dict,
    track_index: int,
) -> None:
    """Open one essential song while retaining the reader's chapter position."""
    essential = chapter["essential_tracks"][track_index]
    track = next(
        item for item in album["tracks"] if item["title"] == essential["title"]
    )
    open_journey_album_track(
        universe,
        album,
        track,
        guided_track_index=track_index,
    )


def open_journey_album_track(
    universe: dict,
    album: dict,
    track: dict,
    *,
    guided_track_index: int | None = None,
) -> None:
    """Open any album song and retain a clear return path to its chapter."""
    youtube_url = track.get("youtube_url") or (
        "https://www.youtube.com/results?search_query="
        + quote_plus(f"{universe['name']} {track['title']} official audio")
    )
    genius_url = track.get("genius_url") or (
        "https://genius.com/search?q="
        + quote_plus(f"{universe['name']} {track['title']}")
    )
    st.session_state.song = {
        **track,
        "artist": universe["name"],
        "album": album["title"],
        "album_year": album["year"],
        "album_sources": album["source_ids"],
        "genius_url": genius_url,
        "youtube_url": youtube_url,
    }
    st.session_state.journey_return = True
    if guided_track_index is None:
        st.session_state.pop("journey_guided_song", None)
    else:
        st.session_state.journey_track_index = guided_track_index
        st.session_state.journey_guided_song = True
    st.session_state.page = "song"


def render_journey_song_navigation(repository: ArchiveRepository) -> None:
    """Keep essential-song reading sequential inside a Tyler chapter."""
    _, universe, chapter, album, release_index = tyler_journey_context(repository)
    track_index = int(st.session_state.get("journey_track_index", 0))
    track_index = max(0, min(track_index, len(chapter["essential_tracks"]) - 1))
    total_tracks = len(chapter["essential_tracks"])
    st.markdown(
        f'<div class="journey-progress-copy"><span>CHAPTER {release_index + 1:02d} · ESSENTIAL SONG {track_index + 1} OF {total_tracks}</span>'
        f'<span>{safe(album["title"])}</span></div>',
        unsafe_allow_html=True,
    )
    previous_column, chapter_column, next_column = st.columns([1.2, 1.6, 1.2])
    if previous_column.button(
        "← Previous song",
        key="journey_previous_song",
        disabled=track_index == 0,
        use_container_width=True,
    ):
        open_journey_track(universe, album, chapter, track_index - 1)
        st.rerun()
    if chapter_column.button(
        "Back to album chapter",
        key="journey_back_to_chapter",
        use_container_width=True,
    ):
        st.session_state.page = "journey"
        st.rerun()
    next_label = "Next essential song →" if track_index < total_tracks - 1 else "Finish this chapter →"
    if next_column.button(
        next_label,
        key="journey_next_song",
        type="primary" if track_index < total_tracks - 1 else "secondary",
        use_container_width=True,
    ):
        if track_index < total_tracks - 1:
            open_journey_track(universe, album, chapter, track_index + 1)
        else:
            st.session_state.page = "journey"
        st.rerun()


def render_tyler_journey(repository: ArchiveRepository) -> None:
    """Render Tyler as the complete reference implementation for guided stories."""
    journey, universe, chapter, album, release_index = tyler_journey_context(repository)
    releases = journey["releases"]
    progress = ((release_index + 1) / len(releases)) * 100

    st.sidebar.markdown("**Tyler, the Creator**")
    st.sidebar.caption("FOLLOW THE STORY · COMPLETE 2009–2025 PATH")
    st.sidebar.markdown(
        f"**Chapter {release_index + 1} of {len(releases)}**  \n"
        f"{album['year']} · {album['title']}"
    )
    if st.sidebar.button("Restart from Bastard", key="journey_restart", use_container_width=True):
        st.session_state.journey_release_index = 0
        st.session_state.journey_track_index = 0
        st.rerun()
    if st.sidebar.button("Explore the artist freely", key="journey_explore", use_container_width=True):
        st.session_state.page = "universe"
        st.session_state.view = "Albums"
        st.session_state.pop("journey_return", None)
        st.session_state.pop("journey_guided_song", None)
        st.rerun()
    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"Reviewed archive {repository.data['archive_version']} · "
        f"{repository.data['reviewed_at']}"
    )

    st.markdown(
        f"""
        <div class="journey-progress-copy">
          <span>FOLLOW THE STORY · CHAPTER {release_index + 1:02d} OF {len(releases):02d}</span>
          <span>{album['year']} · {safe(album['type'])}</span>
        </div>
        <div class="journey-progress-track"><div class="journey-progress-fill" style="width:{progress:.2f}%"></div></div>
        """,
        unsafe_allow_html=True,
    )

    release_columns = st.columns(len(releases))
    for index, release in enumerate(releases):
        release_album = next(
            item for item in universe["albums"] if item["id"] == release["album_id"]
        )
        label = f"● {index + 1:02d}" if index == release_index else f"{index + 1:02d}"
        if release_columns[index].button(
            label,
            key=f"journey_release_{release['album_id']}",
            help=f"{release_album['year']} · {release_album['title']}",
            disabled=index == release_index,
            use_container_width=True,
        ):
            st.session_state.journey_release_index = index
            st.session_state.journey_track_index = 0
            st.rerun()

    st.markdown(
        f"""
        <section class="journey-hero">
          <div class="journey-hero-copy">
            <div class="eyebrow">{album['year']} · {safe(album['type'])} · CHAPTER {release_index + 1}</div>
            <h1>{safe(album['title'])}</h1>
            <h2>{safe(chapter['chapter_title'])}</h2>
            <p>{safe(journey['dek'])}</p>
          </div>
          <figure class="journey-portrait">
            <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/f/fa/Tyler_the_Creator_2022_cropped.png/960px-Tyler_the_Creator_2022_cropped.png" alt="Tyler, the Creator performing onstage in 2022">
            <figcaption>Photo: <a href="https://commons.wikimedia.org/wiki/File:Tyler_the_Creator_2022_cropped.png" target="_blank" rel="noopener noreferrer">Raph_PH / Wikimedia Commons</a> · CC BY 2.0</figcaption>
          </figure>
        </section>
        """,
        unsafe_allow_html=True,
    )

    before_column, meaning_column = st.columns(2, gap="large")
    before_column.markdown(
        f'<div class="chapter-context"><div class="eyebrow">Before this release</div>'
        f'<h3>Where the story stands</h3><p>{safe(album["before"])}</p></div>',
        unsafe_allow_html=True,
    )
    meaning_column.markdown(
        f'<div class="chapter-context"><div class="eyebrow">The creative turn</div>'
        f'<h3>Why this chapter matters</h3><p>{safe(album["summary"])}</p></div>',
        unsafe_allow_html=True,
    )

    chapter_sources = repository.sources_for(album["source_ids"])
    if chapter_sources:
        st.caption("OPEN THE EVIDENCE")
        source_columns = st.columns(min(3, len(chapter_sources)))
        for source_index, source in enumerate(chapter_sources):
            source_columns[source_index % len(source_columns)].link_button(
                f"{source['publisher']} source ↗",
                source["url"],
                use_container_width=True,
            )

    connections = album.get("connections", [])
    if connections:
        section(
            "Follow a thread",
            "People and groups in this chapter",
            "These are navigation points, not name drops. Open one to continue through the connected catalog or story.",
        )
        connection_columns = st.columns(min(4, len(connections)))
        for connection_index, connection in enumerate(connections):
            with connection_columns[connection_index % len(connection_columns)]:
                st.markdown(
                    f'<div class="metric-card"><strong>{safe(connection["name"])}</strong>'
                    f'<span>{safe(connection["role"])}</span></div>',
                    unsafe_allow_html=True,
                )
                if st.button(
                    f"Open {connection['name']} →",
                    key=f"journey_connection_{album['id']}_{connection_index}",
                    use_container_width=True,
                ):
                    target_id = connection.get("universe_id")
                    if target_id and repository.get_universe(target_id):
                        open_local_universe(target_id)
                    else:
                        open_artist_by_name(repository, connection["name"])
                    st.rerun()

    section(
        "Listen in sequence",
        "Three essential songs",
        "Open these in order. Each song has one listening cue that connects it to this chapter’s larger change.",
    )
    track_lookup = {track["title"]: track for track in album["tracks"]}
    song_columns = st.columns(3, gap="medium")
    for track_index, essential in enumerate(chapter["essential_tracks"]):
        track = track_lookup[essential["title"]]
        with song_columns[track_index]:
            st.markdown(
                f'<article class="essential-card"><div class="essential-number">ESSENTIAL {track_index + 1:02d}</div>'
                f'<h3>{safe(essential["title"])}</h3><p>{safe(essential["focus"])}</p>'
                f'<div class="essential-theme">{safe(track["theme"])}</div></article>',
                unsafe_allow_html=True,
            )
            if st.button(
                "Open song →",
                key=f"journey_song_{album['id']}_{track_index}",
                use_container_width=True,
            ):
                open_journey_track(universe, album, chapter, track_index)
                st.rerun()

    section(
        "Complete tracklist",
        f"Every song on {album['title']}",
        "Nothing is hidden behind the guided path. Open any song’s Threadline page, listen on YouTube, or continue to its licensed lyrics reference.",
    )
    essential_titles = {
        essential["title"] for essential in chapter["essential_tracks"]
    }
    for catalog_index, track in enumerate(album["tracks"], start=1):
        youtube_url = track.get("youtube_url") or (
            "https://www.youtube.com/results?search_query="
            + quote_plus(f"{universe['name']} {track['title']} official audio")
        )
        genius_url = track.get("genius_url") or (
            "https://genius.com/search?q="
            + quote_plus(f"{universe['name']} {track['title']}")
        )
        with st.container(border=True):
            number_column, title_column, story_column, listen_column, lyrics_column = st.columns(
                [0.42, 3.1, 1.15, 1.05, 1.05],
                vertical_alignment="center",
            )
            number_column.markdown(f"**{catalog_index:02d}**")
            title_column.markdown(f"**{track['title']}**")
            title_column.caption(
                ("ESSENTIAL · " if track["title"] in essential_titles else "")
                + track.get("theme", "Song catalog entry")
            )
            if story_column.button(
                "Open song →",
                key=f"journey_catalog_song_{album['id']}_{catalog_index}",
                use_container_width=True,
            ):
                open_journey_album_track(universe, album, track)
                st.rerun()
            listen_column.link_button(
                "Listen ↗",
                youtube_url,
                use_container_width=True,
            )
            lyrics_column.link_button(
                "Lyrics ↗",
                genius_url,
                use_container_width=True,
            )

    st.markdown(
        f'<article class="transition-card"><div class="eyebrow">What changes next</div>'
        f'<h3>{"Complete the current story" if release_index == len(releases) - 1 else "Carry this into the next release"}</h3>'
        f'<p>{safe(chapter["transition"])}</p></article>',
        unsafe_allow_html=True,
    )
    previous_column, album_column, next_column = st.columns([1.2, 1.2, 1.6])
    if previous_column.button(
        "← Previous release",
        key="journey_previous",
        disabled=release_index == 0,
        use_container_width=True,
    ):
        st.session_state.journey_release_index = release_index - 1
        st.session_state.journey_track_index = 0
        st.rerun()
    if album_column.button(
        "Dedicated album page",
        key="journey_full_album",
        use_container_width=True,
    ):
        st.session_state.selected_album_id = album["id"]
        st.session_state.journey_return = True
        st.session_state.pop("journey_guided_song", None)
        st.session_state.page = "album"
        st.rerun()
    with next_column.container(key="journey_next"):
        if release_index < len(releases) - 1:
            next_album = next(
                item
                for item in universe["albums"]
                if item["id"] == releases[release_index + 1]["album_id"]
            )
            if st.button(
                f"Next: {next_album['title']} →",
                key="journey_next_release",
                type="primary",
                use_container_width=True,
            ):
                st.session_state.journey_release_index = release_index + 1
                st.session_state.journey_track_index = 0
                st.rerun()
        elif st.button(
            "Explore every album →",
            key="journey_complete",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.page = "universe"
            st.session_state.view = "Albums"
            st.session_state.pop("journey_return", None)
            st.session_state.pop("journey_guided_song", None)
            st.rerun()


def render_home(repository: ArchiveRepository) -> None:
    st.markdown(
        """
        <section class="home-hero">
          <div class="eyebrow">A connected music-story platform</div>
          <h1>Search an artist.<br><em>Follow every thread.</em></h1>
          <p>Begin with anyone. Explore their catalog, then move through the groups,
          relationships, public statements, albums, and events that shaped the music.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if st.button(
        "Recommend from my Apple Music library",
        type="primary",
        key="apple_music_cta",
    ):
        st.session_state.page = "library"
        st.rerun()
    with st.form("global-artist-search", border=False):
        search_columns = st.columns([5, 1])
        with search_columns[0]:
            query = st.text_input(
                "Search any artist, group, or collective",
                value=st.session_state.get("search_query", ""),
                placeholder="Try Yeat, Beyoncé, Radiohead, or The Internet",
                label_visibility="collapsed",
            )
        with search_columns[1]:
            submitted = st.form_submit_button("Search", use_container_width=True)

    if submitted:
        clean_query = " ".join(query.split())
        if not clean_query:
            st.warning("Enter an artist, group, or collective.")
        else:
            st.session_state.search_query = clean_query
            with st.spinner("Searching the artist catalog…"):
                external = search_catalog(clean_query)
            st.session_state.search_results = {
                "local": [item["id"] for item in repository.find_universes(clean_query)],
                "external": external,
            }

    results = st.session_state.get("search_results")
    if not results:
        render_featured_story()
    if results:
        local_universes = [
            repository.get_universe(universe_id)
            for universe_id in results.get("local", [])
            if repository.get_universe(universe_id)
        ]
        local_names = {universe["name"].casefold() for universe in local_universes}
        external = results.get("external", {})
        external_artists = [
            artist
            for artist in external.get("artists", [])
            if artist["name"].casefold() not in local_names
        ]
        section(
            "Search results",
            f"Artists matching “{st.session_state.get('search_query', '')}”",
            "Reviewed stories open the narrative archive. Synchronized member catalogs open complete local release and song indexes; other matches use a universal catalog profile.",
        )
        if external.get("status") == "provider-error":
            st.warning(external.get("message"))
        combined = [
            (
                "reviewed" if item.get("reviewed", True) else "local-catalog",
                item,
            )
            for item in local_universes
        ] + [
            ("catalog", item) for item in external_artists
        ]
        if not combined:
            st.info("No artist identity matched that search. Try a stage name or alternate spelling.")
        columns = st.columns(3)
        for index, (result_type, item) in enumerate(combined[:9]):
            with columns[index % 3]:
                if result_type in {"reviewed", "local-catalog"}:
                    detail = item["summary"]
                    badge = (
                        "REVIEWED STORY"
                        if result_type == "reviewed"
                        else "SYNCED MEMBER CATALOG"
                    )
                    badge_class = (
                        "reviewed-badge"
                        if result_type == "reviewed"
                        else "catalog-badge"
                    )
                    st.markdown(
                        f'<div class="result-card"><div class="{badge_class}">{badge}</div>'
                        f'<h3>{safe(item["name"])}</h3><p>{safe(detail)}</p></div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("Open universe", key=f"home-local-{item['id']}", use_container_width=True):
                        open_local_universe(item["id"])
                        st.rerun()
                else:
                    location = item.get("area") or item.get("country") or "Location not listed"
                    detail = " · ".join(
                        part for part in [item.get("artist_type"), location, item.get("disambiguation")] if part
                    )
                    st.markdown(
                        f'<div class="result-card"><div class="catalog-badge">CATALOG MATCH · {item.get("score", 0)}%</div>'
                        f'<h3>{safe(item["name"])}</h3><p>{safe(detail)}</p></div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("View artist", key=f"home-catalog-{item['mbid']}", use_container_width=True):
                        open_catalog_universe(item)
                        st.rerun()

    section(
        "One search, different depths",
        "Every artist has an entrance",
        "The universal catalog answers who and what. Reviewed Threadline stories add the sourced how and why.",
    )
    principles = [
        ("Universal catalog", "Search any artist identity and browse album or EP release groups."),
        ("Reviewed stories", "Polished chapters connect public events, statements, people, albums, and songs."),
        ("Living connections", "Move across solo artists, groups, collaborators, and scenes without returning home."),
    ]
    columns = st.columns(3)
    for column, (title, body) in zip(columns, principles):
        column.markdown(
            f'<div class="principle-card"><strong>{safe(title)}</strong><p>{safe(body)}</p></div>',
            unsafe_allow_html=True,
        )


def render_library(repository: ArchiveRepository) -> None:
    """Recommend a track from a user-supplied Apple Music metadata export."""

    st.markdown(
        """
        <section class="home-hero" style="padding-top:2rem">
          <div class="eyebrow">Your library · your entrance</div>
          <h1 style="font-size:clamp(3.2rem,8vw,6.8rem)">Pick a song.<br><em>Follow its story.</em></h1>
          <p>Threadline reads the listening signals already in your Apple Music
          library, explains one transparent recommendation, then opens the artist's
          reviewed story or catalog universe.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    demo_columns = st.columns([1.05, 1.95])
    demo_clicked = demo_columns[0].button(
        "▶ Launch the live demo",
        type="primary",
        use_container_width=True,
    )
    demo_columns[1].markdown(
        "**No personal export needed.** Load a clearly labeled sample playlist and "
        "run the same profile, candidate-generation, hybrid-ranking, and story flow "
        "used for an uploaded library."
    )
    if demo_clicked:
        st.session_state.library_source = "demo"
        st.session_state.pop("playlist_continuation_result", None)

    with st.expander("Or use your own Apple Music library", expanded=False):
        st.markdown(
            "1. Open **Music** on your Mac.\n"
            "2. Choose **File → Library → Export Library** for everything, or select "
            "a playlist and choose **Export Playlist**.\n"
            "3. Choose **XML**, then upload that file below."
        )
        st.caption(
            "Apple exports metadata, not the audio files. Threadline keeps only title, "
            "artist, album, genre, play count, skip count, rating, and dates. The file "
            "is processed for this app session and is not written to the project."
        )

        uploaded = st.file_uploader(
            "Apple Music library or playlist export (.xml)",
            type=["xml"],
            help=(
                "For a deployed copy, the file is processed by that Streamlit server. "
                "Run Threadline locally if you want the metadata to remain on your Mac."
            ),
        )

    upload_payload = uploaded.getvalue() if uploaded else None
    upload_digest = (
        hashlib.sha256(upload_payload).hexdigest()[:12] if upload_payload else None
    )
    if upload_digest and upload_digest != st.session_state.get("library_upload_digest"):
        st.session_state.library_upload_digest = upload_digest
        st.session_state.library_source = "upload"
        st.session_state.pop("playlist_continuation_result", None)

    source = st.session_state.get("library_source")
    if source == "demo":
        library_export = demo_apple_music_export()
        source_digest = "threadline-live-demo-v1"
        st.success(
            "Live demo loaded · Late Night: Alternative R&B · six public sample tracks. "
            "No personal listening data is being used."
        )
    elif source == "upload" and upload_payload:
        try:
            library_export = parse_apple_music_export(upload_payload)
        except AppleMusicImportError as exc:
            st.error(str(exc))
            return
        source_digest = upload_digest or "uploaded-library"
    else:
        st.markdown(
            '<div class="empty-note"><strong>No library loaded</strong><br>'
            "Launch the safe demo above, or upload your own export. Artist search and "
            "reviewed stories work without either.</div>",
            unsafe_allow_html=True,
        )
        return

    tracks = list(library_export.tracks)
    profile = analyze_library(tracks)
    section(
        "Library profile",
        "A taste profile made from evidence",
        "The profile weights recorded plays most heavily, then ratings. Missing metadata stays missing—Threadline does not invent mood or audio features.",
    )
    metrics = [
        (profile.track_count, "music tracks"),
        (profile.artist_count, "artists"),
        (profile.genre_count, "genres"),
    ]
    metric_columns = st.columns(3)
    for column, (value, label) in zip(metric_columns, metrics):
        column.markdown(
            f'<div class="metric-card"><strong>{value}</strong><span>{safe(label)}</span></div>',
            unsafe_allow_html=True,
        )

    profile_columns = st.columns(2)
    with profile_columns[0]:
        st.markdown("**Strongest genres in this export**")
        st.write(" · ".join(name for name, _ in profile.top_genres) or "No genres listed")
    with profile_columns[1]:
        st.markdown("**Strongest artists in this export**")
        st.write(" · ".join(name for name, _ in profile.top_artists) or "No artists listed")

    render_playlist_continuation(
        repository,
        library_export,
        source_digest=source_digest,
        demo_mode=source == "demo",
    )

    section(
        "Transparent recommendation",
        "Choose what kind of return you want",
        "Every mode uses the same imported metadata with different published weights.",
    )
    controls = st.columns([1.1, 1.1, 0.8])
    with controls[0]:
        mode = st.selectbox("Mode", RECOMMENDATION_MODES)
    genres = sorted({track.genre for track in tracks}, key=str.casefold)
    with controls[1]:
        genre_choice = st.selectbox("Genre scope", ["All genres", *genres])
    with controls[2]:
        recommendation_count = st.slider("Number of picks", 1, 5, 3)

    mode_help = {
        "Rediscover": "Prioritizes time away, then your strongest genres and positive history.",
        "Comfort pick": "Prioritizes familiar, repeatedly played tracks with positive history.",
        "Deep cut": "Prioritizes less-played tracks inside genres your library already supports.",
    }
    st.caption(mode_help[mode])
    recommendations = recommend_from_library(
        tracks,
        mode=mode,
        genre=None if genre_choice == "All genres" else genre_choice,
        limit=recommendation_count,
    )
    if not recommendations:
        st.info("No tracks match that genre scope.")
        return

    for index, recommendation in enumerate(recommendations, start=1):
        track = recommendation.track
        reasons = "".join(f"<li>{safe(reason)}</li>" for reason in recommendation.reasons)
        st.markdown(
            f'<article class="library-card"><span class="score-pill">PICK {index} · {recommendation.score:.2f}/10</span>'
            f'<h3>{safe(track.title)}</h3><p>{safe(track.artist)} · {safe(track.album)} · {safe(track.genre)}</p>'
            f'<ul>{reasons}</ul></article>',
            unsafe_allow_html=True,
        )
        action_columns = st.columns([1, 2])
        if action_columns[0].button(
            f"Follow {track.artist}'s story",
            key=f"library-story-{track.library_id}-{index}",
            use_container_width=True,
            type="primary" if index == 1 else "secondary",
        ):
            open_artist_by_name(repository, track.artist)
            st.rerun()
        with action_columns[1].expander("Inspect the score"):
            for signal, value in recommendation.breakdown.items():
                st.write(f"{signal.title()}: {value:.0%}")
            st.caption(
                "The displayed recommendation score is a weighted ranking signal, "
                "not a probability that you will enjoy the track."
            )


def render_playlist_continuation(
    repository: ArchiveRepository,
    library_export: AppleMusicExport,
    *,
    source_digest: str,
    demo_mode: bool = False,
) -> None:
    """Recommend new tracks that fit one selected Apple Music playlist."""

    section(
        "Automatic playlist continuation",
        "Recommend a song to a playlist",
        "The first stage finds similar tracks from public listening patterns. The second checks the whole playlist's mood, multi-song support, your library affinity, and discovery value.",
    )
    if not library_export.playlists:
        st.info(
            "This export contains tracks but no named playlist membership. Export the "
            "full library or a specific playlist as XML to use playlist continuation."
        )
        return

    playlist_options = list(library_export.playlists)
    selected_playlist = st.selectbox(
        "Playlist to continue",
        playlist_options,
        format_func=lambda item: (
            f"{item.name} · {len(library_export.tracks_for(item))} tracks"
        ),
        key="continuation-playlist",
    )
    playlist_tracks = library_export.tracks_for(selected_playlist)
    if len(playlist_tracks) < 2:
        st.warning("Add at least two identifiable music tracks before continuing this playlist.")
        return

    seed_preview = []
    seen_artists = set()
    for track in playlist_tracks:
        if track.artist.casefold() not in seen_artists:
            seed_preview.append(track.artist)
            seen_artists.add(track.artist.casefold())
        if len(seed_preview) == 6:
            break
    st.caption(
        "Representative artists: " + " · ".join(seed_preview)
        + ". Candidate explanations use provider similarity scores—not invented fan-overlap percentages."
    )

    api_key_configured = bool(os.getenv("LASTFM_API_KEY", "").strip())
    provider_mode = "lastfm" if api_key_configured else "demo"
    request_key = (
        source_digest,
        selected_playlist.persistent_id,
        tuple(track.library_id for track in playlist_tracks),
        provider_mode,
    )
    if not api_key_configured and not demo_mode:
        st.info(
            "Listening-based candidate generation is ready but not configured. Create a "
            "Last.fm API key, set `LASTFM_API_KEY`, and restart Streamlit. The read-only "
            "similar-track and tag endpoints do not require a listener login."
        )
        st.link_button(
            "Create a Last.fm API account ↗",
            "https://www.last.fm/api/account/create",
        )
        return

    if demo_mode and not api_key_configured:
        st.info(
            "Stakeholder demo mode uses bundled public sample similarity evidence, "
            "then runs the same hybrid ranker and explanations as the live provider. "
            "Configure Last.fm to replace the sample evidence with current lookups."
        )

    action_columns = st.columns([1, 2])
    generate = action_columns[0].button(
        "Generate hybrid matches" if demo_mode and not api_key_configured
        else "Find playlist matches",
        type="primary",
        use_container_width=True,
    )
    if demo_mode and not api_key_configured:
        action_columns[1].caption(
            "This walkthrough is deterministic and sends no data externally. The "
            "candidate evidence is fixed; profiling, aggregation, scoring, diversity, "
            "explanations, and story navigation are the production code path."
        )
    else:
        action_columns[1].caption(
            "When you click, Threadline sends up to six representative artist/title pairs "
            "and shortlisted candidate names to Last.fm for similarity and tags. It then "
            "reranks locally; the complete library export is never sent."
        )
    if generate:
        try:
            with st.spinner("Comparing listening neighborhoods and playlist mood…"):
                client = (
                    LastfmClient(os.environ["LASTFM_API_KEY"])
                    if api_key_configured
                    else DemoSimilarityClient()
                )
                recommender = HybridPlaylistRecommender(client)
                results = recommender.recommend(
                    selected_playlist.name,
                    playlist_tracks,
                    library_export.tracks,
                    limit=5,
                )
            st.session_state.playlist_continuation_result = {
                "request_key": request_key,
                "results": results,
            }
        except PlaylistRecommendationError as exc:
            st.session_state.pop("playlist_continuation_result", None)
            st.error(str(exc))
            return

    stored = st.session_state.get("playlist_continuation_result")
    if not stored or stored.get("request_key") != request_key:
        return
    results = stored.get("results", [])
    if not results:
        st.warning(
            "The provider did not return enough supported tracks for this playlist. "
            "Try a playlist with more identifiable songs or artists."
        )
        return

    st.subheader("Best playlist matches")
    for index, recommendation in enumerate(results, start=1):
        reasons = "".join(f"<li>{safe(reason)}</li>" for reason in recommendation.reasons)
        tags = " · ".join(recommendation.tags[:5]) or "No community tags returned"
        st.markdown(
            f'<article class="library-card"><span class="score-pill">MATCH {index} · {recommendation.score:.2f}/10 · {safe(recommendation.confidence.upper())}</span>'
            f'<h3>{safe(recommendation.title)}</h3><p>{safe(recommendation.artist)} · {safe(tags)}</p>'
            f'<ul>{reasons}</ul></article>',
            unsafe_allow_html=True,
        )
        buttons = st.columns([1, 1, 1.3])
        buttons[0].link_button(
            "Open candidate ↗",
            recommendation.url
            or "https://www.last.fm/search?q="
            + quote_plus(f"{recommendation.artist} {recommendation.title}"),
            use_container_width=True,
        )
        buttons[1].link_button(
            "Find on Apple Music ↗",
            "https://music.apple.com/us/search?term="
            + quote_plus(f"{recommendation.artist} {recommendation.title}"),
            use_container_width=True,
        )
        if buttons[2].button(
            f"Follow {recommendation.artist}'s story",
            key=f"continuation-story-{selected_playlist.persistent_id}-{index}",
            use_container_width=True,
        ):
            open_artist_by_name(repository, recommendation.artist)
            st.rerun()
        with st.expander(
            f"Inspect {recommendation.title}'s hybrid score",
        ):
            for signal, value in recommendation.breakdown.items():
                st.write(f"{signal.title()}: {value:.0%}")
            st.caption(
                "This is a playlist-fit ranking, not a claim that a fixed percentage of "
                "an artist's fans like another artist. Directly adding tracks to Apple "
                "Music requires a separate MusicKit authorization flow."
            )


def render_header(universe: dict) -> None:
    accent = safe(universe["accent"])
    secondary = safe(universe["accent_secondary"])
    chips = "".join(f'<span class="chip">{safe(item)}</span>' for item in universe["genres"])
    st.markdown(
        f"""
        <section class="hero" style="background: linear-gradient(128deg, {accent}, {secondary});">
          <div class="eyebrow">{safe(universe['kind'])} · {safe(universe['coverage'])}</div>
          <h1>{safe(universe['name'])}</h1>
          <p>{safe(universe['tagline'])}</p>
          <div class="meta-row">{chips}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def section(kicker: str, title: str, description: str = "") -> None:
    st.markdown(
        f'<div class="section-label">{safe(kicker)}</div>'
        f'<h2 class="section-title">{safe(title)}</h2>'
        + (f'<p class="lede">{safe(description)}</p>' if description else ""),
        unsafe_allow_html=True,
    )


def source_cards(repository: ArchiveRepository, source_ids: list[str]) -> None:
    for source in repository.sources_for(source_ids):
        st.markdown(
            f"""
            <div class="source-card">
              <a href="{safe(source['url'])}" target="_blank">{safe(source['title'])} ↗</a>
              <div class="source-meta">{safe(source['publisher'])} · {safe(source['published_at'])} · {safe(source['source_type'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_tyler_gallery() -> None:
    """Show a compact, credited visual timeline on Tyler's reviewed page."""
    section(
        "Visual archive",
        "Tyler, the Creator across the years",
        "Performance photography adds a human entry point alongside the reviewed discography.",
    )
    st.markdown(
        """
        <div class="artist-photo-grid">
          <figure class="artist-photo">
            <img
              src="https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Tyler%2C_The_Creator_%288048745695%29.jpg/1280px-Tyler%2C_The_Creator_%288048745695%29.jpg"
              alt="Tyler, the Creator performing in Los Angeles in 2012"
            >
            <figcaption>2012 · Photo: <a href="https://commons.wikimedia.org/wiki/File:Tyler,_The_Creator_(8048745695).jpg" target="_blank" rel="noopener noreferrer">Incase / Wikimedia Commons</a> · CC BY 2.0</figcaption>
          </figure>
          <figure class="artist-photo">
            <img
              src="https://upload.wikimedia.org/wikipedia/commons/thumb/f/fa/Tyler_the_Creator_2022_cropped.png/960px-Tyler_the_Creator_2022_cropped.png"
              alt="Tyler, the Creator performing in 2022"
            >
            <figcaption>2022 · Photo: <a href="https://commons.wikimedia.org/wiki/File:Tyler_the_Creator_2022_cropped.png" target="_blank" rel="noopener noreferrer">Raph_PH / Wikimedia Commons</a> · CC BY 2.0</figcaption>
          </figure>
          <figure class="artist-photo">
            <img
              src="https://upload.wikimedia.org/wikipedia/commons/thumb/c/ce/Tyler_The_Creator.jpg/1280px-Tyler_The_Creator.jpg"
              alt="Tyler, the Creator performing in New York in 2025"
            >
            <figcaption>2025 · Photo: <a href="https://commons.wikimedia.org/wiki/File:Tyler_The_Creator.jpg" target="_blank" rel="noopener noreferrer">Dunkwatkin / Wikimedia Commons</a> · CC0</figcaption>
          </figure>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _visual_name(value: object) -> str:
    return str(value or "").translate(str.maketrans("‐–—", "---")).casefold()


def _odd_future_visuals(repository: ArchiveRepository, universe: dict) -> list[dict]:
    """Collect one licensed portrait plus official-video stills when available."""
    visuals: list[dict] = []
    seen_video_ids: set[str] = set()
    photo = ODD_FUTURE_COMMONS_PHOTOS.get(universe.get("id"))
    if photo:
        image_url, source_url, credit = photo
        visuals.append(
            {
                "image_url": image_url,
                "source_url": source_url,
                "caption": f"Photo: {credit}",
                "alt": f"{universe['name']} photographed or performing",
            }
        )

    def add_tracks(source_universe: dict, require_credit: bool) -> None:
        target = _visual_name(universe.get("name"))
        for album in source_universe.get("albums", []):
            for track in album.get("tracks", []):
                video_id = str(track.get("youtube_id") or "")
                if not video_id or video_id in seen_video_ids:
                    continue
                credits = track.get("performers", []) + track.get("featured_artists", [])
                if require_credit and target not in {_visual_name(name) for name in credits}:
                    continue
                seen_video_ids.add(video_id)
                visuals.append(
                    {
                        "image_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                        "source_url": track.get("youtube_url")
                        or f"https://www.youtube.com/watch?v={video_id}",
                        "caption": f"{track.get('title', 'Official video')} · official-video still",
                        "alt": f"Official-video thumbnail for {track.get('title', 'a track')} by {universe['name']}",
                    }
                )
                if len(visuals) >= 3:
                    return

    add_tracks(universe, require_credit=False)
    if len(visuals) < 3:
        for connected_universe in repository.data.get("universes", []):
            add_tracks(connected_universe, require_credit=True)
            if len(visuals) >= 3:
                break

    context_fallbacks = [
        {
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/fa/Tyler_the_Creator_2022_cropped.png/960px-Tyler_the_Creator_2022_cropped.png",
            "source_url": "https://commons.wikimedia.org/wiki/File:Tyler_the_Creator_2022_cropped.png",
            "caption": "Odd Future visual context · Raph_PH · CC BY 2.0",
            "alt": "Tyler, the Creator performing as Odd Future visual context",
        },
        {
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/d/d3/Jasper_Dolphin_%28cropped%29.jpg",
            "source_url": "https://commons.wikimedia.org/wiki/File:Jasper_Dolphin_(cropped).jpg",
            "caption": "Odd Future visual context · Mileslwayne · CC BY 4.0",
            "alt": "Jasper Dolphin as Odd Future visual context",
        },
        {
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/c/c3/The_Internet.jpg",
            "source_url": "https://commons.wikimedia.org/wiki/File:The_Internet.jpg",
            "caption": "Odd Future visual context · Incase · CC BY 2.0",
            "alt": "The Internet as Odd Future visual context",
        },
    ]
    for fallback in context_fallbacks:
        if len(visuals) >= 3:
            break
        if fallback["image_url"] not in {item["image_url"] for item in visuals}:
            visuals.append(fallback)
    return visuals[:3]


def render_odd_future_gallery(
    repository: ArchiveRepository,
    universe: dict,
) -> None:
    if universe.get("id") == "tyler-the-creator":
        render_tyler_gallery()
        return
    is_connected = (
        universe.get("id") == "odd-future"
        or bool(universe.get("odd_future_role"))
        or "Odd Future" in universe.get("collectives", [])
    )
    if not is_connected:
        return
    visuals = _odd_future_visuals(repository, universe)
    section(
        "Visual archive",
        f"{universe['name']} in pictures",
        "Licensed photography and official-video stills add a visual entrance to the catalog.",
    )
    figures = "".join(
        '<figure class="artist-photo">'
        f'<img src="{safe(item["image_url"])}" alt="{safe(item["alt"])}">'
        f'<figcaption><a href="{safe(item["source_url"])}" target="_blank" rel="noopener noreferrer">{safe(item["caption"])}</a></figcaption>'
        "</figure>"
        for item in visuals
    )
    st.markdown(
        f'<div class="artist-photo-grid">{figures}</div>',
        unsafe_allow_html=True,
    )


def render_overview(repository: ArchiveRepository, universe: dict) -> None:
    render_odd_future_gallery(repository, universe)
    if universe.get("id") != "tyler-the-creator":
        section("The universe", "A map, not a list", universe["summary"])
        counts = [
            (len(universe.get("chapters", [])), "reviewed chapters"),
            (len(universe.get("albums", [])), "album chapters"),
            (len(universe.get("related", [])), "connected universes"),
        ]
        columns = st.columns(3)
        for column, (value, label) in zip(columns, counts):
            column.markdown(
                f'<div class="metric-card"><strong>{value}</strong><span>{safe(label)}</span></div>',
                unsafe_allow_html=True,
            )

    tracks = universe.get("popular_tracks", [])
    if tracks:
        section(
            "Entry points",
            "Songs that open a story",
            "These are editorial entry points in the reviewed demo—not a live popularity chart.",
        )
        for index, track in enumerate(tracks, start=1):
            st.markdown(
                f'<div class="track"><span class="track-num">{index:02d}</span>'
                f'<span><strong>{safe(track["title"])}</strong><br><small>{safe(track["album"])} · {track["year"]}</small></span>'
                f'<span class="track-theme">{safe(" · ".join(track["themes"]))}</span></div>',
                unsafe_allow_html=True,
            )

    section("Editorial boundary", "What the archive will—and will not—claim")
    st.markdown(
        '<div class="archive-note"><span class="status-static">REVIEWED + STATIC</span><br>'
        'The story may report public events and artist statements. It does not infer private '
        'mental states or convert sequence into causation. Critical readings remain optional and labeled.</div>',
        unsafe_allow_html=True,
    )


def render_catalog_overview(repository: ArchiveRepository, universe: dict) -> None:
    render_odd_future_gallery(repository, universe)
    synchronized = universe.get("catalog_generated", False)
    section(
        "Synchronized member catalog" if synchronized else "Universal catalog profile",
        (
            "A complete local catalog; narrative review remains open"
            if synchronized
            else "An entrance, even before the story is reviewed"
        ),
        universe["summary"],
    )
    counts = [
        (len(universe.get("albums", [])), "catalog releases"),
        (universe.get("location", "—"), "associated area"),
        (f"{universe.get('catalog_score', 0)}%", "identity match"),
    ]
    columns = st.columns(3)
    for column, (value, label) in zip(columns, counts):
        column.markdown(
            f'<div class="metric-card"><strong>{safe(value)}</strong><span>{safe(label)}</span></div>',
            unsafe_allow_html=True,
        )
    section("Story status", "Catalog found. Narrative review still open.")
    st.markdown(
        '<div class="archive-note"><span class="catalog-badge">'
        + ("SYNCED MUSIC CATALOG" if synchronized else "EXTERNAL CATALOG METADATA")
        + "</span><br>"
        'This artist is searchable now, but Threadline has not published a reviewed story for them yet. '
        + (
            "Their albums, mixtapes, tracklists, YouTube destinations, and Genius destinations are available locally. "
            if synchronized
            else ""
        )
        + 'The site will not generate a biography from unreviewed catalog metadata.</div>',
        unsafe_allow_html=True,
    )
    st.link_button("Inspect this MusicBrainz identity ↗", universe["catalog_url"])


def render_catalog_discography(universe: dict) -> None:
    section(
        "External catalog",
        f"{universe['name']} release groups",
        "Albums and EPs come from MusicBrainz and may be incomplete. They are catalog metadata, not reviewed Threadline story chapters.",
    )
    releases = universe.get("albums", [])
    if not releases:
        st.info(
            "No album or EP release groups were returned. The artist identity still remains searchable."
        )
        return
    columns = st.columns(4)
    for index, release in enumerate(releases[:24]):
        with columns[index % 4]:
            st.markdown(
                f'<div class="cover" style="background: linear-gradient(145deg, {safe(universe["accent"])}, #242422);">'
                f'{safe(release["title"])}</div>'
                f'<div class="album-title">{safe(release["title"])}</div>'
                f'<div class="album-meta">{safe(release["year"])} · {safe(release["type"])}</div>',
                unsafe_allow_html=True,
            )
            st.link_button(
                "Catalog details ↗",
                release["musicbrainz_url"],
                use_container_width=True,
            )


def open_story_song(
    repository: ArchiveRepository,
    current_universe: dict,
    song_link: dict,
) -> bool:
    """Open a catalog song referenced by a reviewed story chapter."""
    target = repository.get_universe(
        song_link.get("universe_id", current_universe["id"])
    )
    wanted_title = str(song_link.get("track_title", "")).casefold()
    if not target or not wanted_title:
        return False

    for album in target.get("albums", []):
        for track in album.get("tracks", []):
            if str(track.get("title", "")).casefold() != wanted_title:
                continue
            youtube_url = track.get("youtube_url") or (
                "https://www.youtube.com/results?search_query="
                + quote_plus(f"{target['name']} {track['title']} official audio")
            )
            genius_url = track.get("genius_url") or (
                "https://genius.com/search?q="
                + quote_plus(f"{target['name']} {track['title']}")
            )
            st.session_state.song = {
                **track,
                "artist": target["name"],
                "album": album["title"],
                "album_year": album["year"],
                "album_sources": album.get("source_ids", []),
                "genius_url": genius_url,
                "youtube_url": youtube_url,
            }
            st.session_state.universe_id = target["id"]
            st.session_state.page = "song"
            return True
    return False


def render_story(repository: ArchiveRepository, universe: dict) -> None:
    story_title = (
        f"{universe['name']} story"
        if universe["name"].casefold().startswith("the ")
        else f"The {universe['name']} story"
    )
    section(
        "Optional guided path",
        story_title,
        "Follow the reviewed chapters in order, or leave the path at any time through a source or connected universe.",
    )
    chapters = universe.get("chapters", [])
    if not chapters:
        st.markdown(
            '<div class="empty-note">This connected-universe preview does not yet have a reviewed long-form chapter.</div>',
            unsafe_allow_html=True,
        )
        return

    interview_videos = universe.get("interview_videos", [])
    if interview_videos:
        section(
            "Watch the archive",
            "Hear the people behind the story",
            "Curated interviews add their public voices beside the written reporting. Video is not silently converted into quotes or archive evidence.",
        )
        video_columns = st.columns(min(2, len(interview_videos)))
        for index, video in enumerate(interview_videos[:4]):
            with video_columns[index % len(video_columns)]:
                st.video(video["url"])
                st.markdown(f"**{safe(video['title'])}**")
                st.write(video["description"])
                st.caption(
                    f"{video['publisher']} · {video['published_at']} · video interview"
                )
                st.link_button(
                    "Open interview on YouTube ↗",
                    video["url"],
                    use_container_width=True,
                )

    st.markdown('<div class="timeline">', unsafe_allow_html=True)
    for chapter in chapters:
        st.markdown(
            f"""
            <article class="story-card">
              <div class="story-era">{safe(chapter['era'])}</div>
              <h3>{safe(chapter['title'])}</h3>
              <p>{safe(chapter['dek'])}</p>
              <span class="claim">{safe(chapter['claim_type'].replace('-', ' '))}</span>
            </article>
            """,
            unsafe_allow_html=True,
        )
        song_links = chapter.get("song_links", [])
        if song_links:
            link_columns = st.columns(min(3, len(song_links)))
            for index, song_link in enumerate(song_links):
                label = song_link.get("label") or (
                    f"Open {song_link['track_title']}"
                )
                if link_columns[index % len(link_columns)].button(
                    f"♫ {label}",
                    key=(
                        f"story-song-{universe['id']}-{chapter['id']}-{index}"
                    ),
                    use_container_width=True,
                ):
                    if open_story_song(repository, universe, song_link):
                        st.rerun()
                    st.warning("That song is not available in the local catalog yet.")
        with st.expander("Inspect supporting sources"):
            source_cards(repository, chapter["source_ids"])
    st.markdown("</div>", unsafe_allow_html=True)


def render_albums(repository: ArchiveRepository, universe: dict) -> None:
    synchronized = universe.get("catalog_generated", False)
    section(
        "Synchronized discography" if synchronized else "Discography stories",
        "Albums, EPs, and mixtapes" if synchronized else "Albums become chapters",
        (
            "Every synchronized release opens its indexed songs and external playback and lyrics destinations. Reviewed album chapters retain their editorial context."
            if synchronized
            else "The familiar album view gains a reviewed ‘before the album’ layer and source-labeled track themes."
        ),
    )
    albums = universe.get("albums", [])
    if not albums:
        st.markdown(
            '<div class="empty-note">No qualifying album, EP, or mixtape is indexed for this artist yet.</div>',
            unsafe_allow_html=True,
        )
        return

    album_columns = st.columns(4)
    for index, album_option in enumerate(albums):
        with album_columns[index % 4]:
            st.markdown(
                f'<div class="cover" style="background: linear-gradient(145deg, {safe(album_option["accent"])}, #242422);">'
                f'{safe(album_option["title"])}</div>'
                f'<div class="album-title">{safe(album_option["title"])}</div>'
                f'<div class="album-meta">{album_option["year"]} · {safe(album_option["type"])}</div>',
                unsafe_allow_html=True,
            )
            if st.button(
                "Open album" if synchronized else "Open chapter",
                key=f"album-card-{universe['id']}-{album_option['id']}",
                use_container_width=True,
            ):
                st.session_state.selected_album_id = album_option["id"]
                st.session_state.page = "album"
                st.rerun()


def render_album_page(
    repository: ArchiveRepository,
    universe: dict,
    album: dict,
) -> None:
    """Render one reviewed chapter or synchronized catalog release."""
    reviewed_album = bool(album.get("source_ids"))
    page_label = "Album chapter" if reviewed_album else "Catalog release"
    page_note = (
        "A reviewed chapter in the artist’s discography."
        if reviewed_album
        else "Synchronized release metadata; narrative review is still open."
    )
    st.markdown(
        f"""
        <section class="home-hero" style="padding-top:2.4rem">
          <div class="eyebrow">{page_label} · {safe(universe['name'])}</div>
          <h1 style="font-size:clamp(3.2rem,8vw,7rem)">{safe(album['title'])}</h1>
          <p>{album['year']} · {safe(album['type'])} · {page_note}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    left, right = st.columns([0.9, 1.6], gap="large")
    with left:
        st.markdown(
            f'<div class="cover" style="background: linear-gradient(145deg, {safe(album["accent"])}, #242422);">'
            f'{safe(album["title"])}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(f'<div class="album-title">{safe(album["title"])}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="album-meta">{album["year"]} · {safe(album["type"])}</div>',
            unsafe_allow_html=True,
        )
    with right:
        st.subheader("Before the album" if reviewed_album else "Catalog note")
        st.write(album["before"])
        st.subheader("Why this chapter matters" if reviewed_album else "Release coverage")
        st.write(album["summary"])
        if album.get("catalog_complete"):
            st.caption(
                f"Complete catalog index: {len(album['tracks'])} tracks · "
                f"updated {repository.data.get('member_catalog_updated_at') or repository.data.get('track_catalog_updated_at', 'date unavailable')}"
            )
        with st.expander("Sources used for this chapter" if reviewed_album else "Catalog sources"):
            source_cards(repository, album["source_ids"])
            if album.get("tracklist_source_url"):
                st.link_button(
                    "Open tracklist source ↗",
                    album["tracklist_source_url"],
                    use_container_width=True,
                )
            if album.get("youtube_playlist_url"):
                st.link_button(
                    "Open album on YouTube Music ↗",
                    album["youtube_playlist_url"],
                    use_container_width=True,
                )

    connections = album.get("connections", [])
    if connections:
        st.subheader("People connected to this album")
        connection_columns = st.columns(min(4, len(connections)))
        for index, connection in enumerate(connections):
            with connection_columns[index % len(connection_columns)]:
                st.markdown(
                    f'<div class="metric-card"><strong>{safe(connection["name"])}</strong>'
                    f'<span>{safe(connection["role"])}</span></div>',
                    unsafe_allow_html=True,
                )
                if st.button(
                    f"Open {connection['name']}",
                    key=f"album-connection-{album['id']}-{index}",
                    use_container_width=True,
                ):
                    open_artist_by_name(repository, connection["name"])
                    st.rerun()

    st.subheader("Track story index" if reviewed_album else "Track catalog")
    for index, track in enumerate(album["tracks"], start=1):
        track_columns = st.columns([0.35, 4, 2.2, 1.25])
        track_columns[0].markdown(f"**{index:02d}**")
        track_columns[1].markdown(f"### {track['title']}")
        track_columns[2].caption(track["theme"])
        youtube_url = track.get("youtube_url") or (
            "https://www.youtube.com/results?search_query="
            + quote_plus(f"{universe['name']} {track['title']} official audio")
        )
        genius_url = track.get("genius_url") or (
            "https://genius.com/search?q="
            + quote_plus(f"{universe['name']} {track['title']}")
        )
        if track_columns[3].button(
            "Open song",
            key=f"song-{album['id']}-{index}",
            use_container_width=True,
        ):
            st.session_state.song = {
                **track,
                "artist": universe["name"],
                "album": album["title"],
                "album_year": album["year"],
                "album_sources": album["source_ids"],
                "genius_url": genius_url,
                "youtube_url": youtube_url,
            }
            st.session_state.page = "song"
            st.rerun()


def render_karaoke_component(track: dict, cues: list[dict]) -> None:
    """Render an official YouTube embed with progressive lyric highlighting."""
    # Prevent cue text from closing the inline script element.
    cues_json = json.dumps(cues).replace("</", "<\\/")
    video_id = json.dumps(track["youtube_id"])
    component_html = f"""
    <!doctype html>
    <html><head><style>
      * {{ box-sizing:border-box; }}
      body {{ margin:0; background:#0c0c0b; color:#f3efe6; font-family:Inter,Arial,sans-serif; }}
      .video {{ border-radius:22px; overflow:hidden; min-height:440px; background:#000; }}
      #player {{ width:100%; height:440px; }}
      .lyrics {{ margin-top:20px; border:1px solid rgba(255,255,255,.12); border-radius:22px; padding:30px; height:410px; overflow:auto; background:#151514; }}
      .cue {{ opacity:.25; font-size:30px; font-weight:720; line-height:1.22; padding:17px 14px; transition:.2s ease; }}
      .cue.past {{ opacity:.52; }}
      .cue.active {{ opacity:1; transform:scale(1.01); transform-origin:left center; }}
      .lyric-text {{ color:#f3efe6; }}
      .cue.active .lyric-text {{ color:transparent; background-clip:text !important; -webkit-background-clip:text !important; }}
      .section {{ display:block; color:#8e8b84; font-size:10px; text-transform:uppercase; letter-spacing:.15em; margin-bottom:7px; font-weight:800; }}
      @media(max-width:760px) {{ #player,.video{{height:300px;min-height:300px}} .lyrics{{height:360px}} .cue{{font-size:22px}} }}
    </style></head><body>
      <div class="video"><div id="player"></div></div>
      <div class="lyrics" id="lyrics"></div>
      <script>
        const cues = {cues_json}; const lyrics = document.getElementById('lyrics');
        cues.forEach((cue, i) => {{
          const el=document.createElement('div'); el.className='cue'; el.id='cue-'+i;
          const section=document.createElement('span'); section.className='section'; section.textContent=cue.section;
          const text=document.createElement('span'); text.className='lyric-text'; text.textContent=cue.text;
          el.append(section,text);
          lyrics.appendChild(el);
        }});
        let player, previous=-1;
        function onYouTubeIframeAPIReady() {{
          player=new YT.Player('player',{{videoId:{video_id},playerVars:{{playsinline:1}},events:{{onReady:()=>requestAnimationFrame(tick)}}}});
        }}
        function tick() {{ updateCue(); requestAnimationFrame(tick); }}
        function updateCue() {{
          if(!player||!player.getCurrentTime||!cues.length)return;
          const time=player.getCurrentTime(); let active=-1;
          for(let i=0;i<cues.length;i++) if(time>=cues[i].time) active=i;
          document.querySelectorAll('.cue').forEach((el,i)=>{{el.classList.toggle('active',i===active);el.classList.toggle('past',i<active);}});
          if(active>=0){{
            const start=cues[active].time;
            const end=cues[active].end ?? (active+1<cues.length?cues[active+1].time:start+4);
            const progress=Math.max(0,Math.min(100,((time-start)/(end-start))*100));
            const text=document.querySelector('#cue-'+active+' .lyric-text');
            text.style.background='linear-gradient(90deg,#d9ff55 '+progress+'%,#f3efe6 '+progress+'%)';
            if(active!==previous){{document.getElementById('cue-'+active).scrollIntoView({{behavior:'auto',block:'center'}});previous=active;}}
          }}
        }}
      </script>
      <script src="https://www.youtube.com/iframe_api"></script>
    </body></html>
    """
    components.html(component_html, height=890, scrolling=False)


def render_song_background(repository: ArchiveRepository, track: dict) -> None:
    """Place evidence-labeled artist context directly below the lyric player."""
    context_index = load_song_contexts(SONG_CONTEXT_PATH.stat().st_mtime_ns)
    context = build_song_context(repository.data, context_index, track)
    if context.get("status") != "ok":
        st.info(context.get("message", "Reviewed listening context is not available yet."))
        return

    claim_labels = {
        "artist-stated": "Artist statement",
        "documented-fact": "Documented fact",
        "reported": "Reported context",
        "critical-interpretation": "Critical interpretation",
        "evidence-boundary": "Evidence boundary",
    }
    section(
        "Reviewed listening context",
        "Before this song: what was happening around the artist",
        "Album background establishes the shared era. Song background appears separately only when a reviewed source discusses that track.",
    )

    album_background = context.get("album_background", context["primary"])
    song_background = context.get("song_background")
    layers = [("Album background", album_background)]
    if song_background:
        layers.append(("Song background", song_background))

    for layer_name, background in layers:
        claim_label = claim_labels.get(
            background.get("claim_type"),
            background.get("claim_type", "Reviewed context"),
        )
        st.markdown(
            '<div class="song-context-lead">'
            f'<div class="context-badge">{safe(layer_name)} · {safe(claim_label)}</div>'
            f'<h3>{safe(background["title"])}</h3>'
            f'<p>{safe(background["summary"])}</p>'
            f'<div class="context-timing">{safe(background.get("statement_timing", "Reviewed release context"))}</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="context-boundary"><strong>{safe(layer_name)} evidence boundary:</strong> {safe(background["boundary"])}</div>',
            unsafe_allow_html=True,
        )

    performer_threads = context.get("performer_threads", [])
    if performer_threads:
        st.subheader("What each credited artist had publicly established by this point")
        st.caption(
            "A track can hold several perspectives. Each card keeps that person's reviewed thread separate."
        )
        columns = st.columns(2)
        for index, thread in enumerate(performer_threads):
            thread_label = claim_labels.get(
                thread.get("claim_type"), thread.get("claim_type", "Context")
            )
            with columns[index % 2]:
                st.markdown(
                    '<div class="song-voice-card">'
                    f'<div class="context-badge">{safe(thread["artist"])} · {safe(thread_label)}</div>'
                    f'<h3>{safe(thread["title"])}</h3>'
                    f'<p>{safe(thread["summary"])}</p>'
                    "</div>",
                    unsafe_allow_html=True,
                )

    nearby_releases = context.get("nearby_releases", [])
    if nearby_releases:
        st.subheader("What friends were releasing nearby")
        st.caption(context["nearby_release_note"])
        release_columns = st.columns(3)
        for index, release in enumerate(nearby_releases):
            with release_columns[index % 3]:
                st.markdown(
                    '<div class="nearby-release-card">'
                    f'<div class="context-badge">{safe(release["year"])} · {safe(release["type"])}</div>'
                    f'<h3>{safe(release["title"])}</h3>'
                    f'<p>{safe(release["artist"])}</p>'
                    "</div>",
                    unsafe_allow_html=True,
                )

    with st.expander("Sources for this listening context"):
        source_cards(repository, context.get("source_ids", []))
        st.caption(
            f"Static reviewed context · version {context_index.get('context_version', 'unknown')} · reviewed {context.get('reviewed_at') or 'date unavailable'}"
        )


def render_song_page(repository: ArchiveRepository, track: dict) -> None:
    st.markdown(
        f"""
        <section class="home-hero" style="padding-top:2rem">
          <div class="eyebrow">Song story · {safe(track['album'])} · {safe(track['album_year'])}</div>
          <h1 style="font-size:clamp(3rem,7vw,6rem)">{safe(track['title'])}</h1>
          <p>{safe(track['artist'])} · {safe(track['theme'])}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    lyrics_result = load_lrclib_lyrics(
        track["title"], track["artist"], track["album"]
    )
    lrclib_cues = lyrics_result.get("cues", [])
    cues = lrclib_cues or track.get("sync_cues", [])
    using_lrclib_sync = bool(lrclib_cues)

    if using_lrclib_sync:
        st.markdown(
            f'<p><span class="status-live">LIVE LYRIC DATA · {len(lrclib_cues)} TIMED LINES</span> · '
            'Threadline karaoke engine active</p>',
            unsafe_allow_html=True,
        )

    if track.get("youtube_id"):
        if cues:
            render_karaoke_component(track, cues)
        else:
            st.video(f"https://www.youtube.com/watch?v={track['youtube_id']}")
            st.info(
                "Official artist-channel audio/video is ready. LRCLIB does not "
                "currently have a confident synchronized-lyrics match for this recording."
            )
    else:
        st.markdown(
            '<div class="empty-note"><strong>Verified embeddable video pending</strong><br>'
            'Threadline will not embed an unofficial upload. Use the YouTube search below while an official video ID is reviewed.</div>',
            unsafe_allow_html=True,
        )

    if lyrics_result.get("status") == "matched":
        if using_lrclib_sync:
            if not track.get("youtube_id"):
                static_lyrics = lyrics_result.get("plain_lyrics") or "\n".join(
                    cue["text"] for cue in lrclib_cues
                )
                with st.expander("Read lyrics supplied by LRCLIB", expanded=True):
                    st.text(static_lyrics)
            st.caption(
                "LRCLIB supplies the lyric text and line timestamps. Threadline reads the "
                "YouTube player clock, selects and scrolls the active line, and interpolates "
                "the karaoke fill during playback. Provider text is not stored in the archive."
            )
        elif lyrics_result.get("plain_lyrics"):
            with st.expander("Read lyrics from LRCLIB", expanded=True):
                st.text(lyrics_result["plain_lyrics"])
            st.caption(
                "Plain lyrics loaded on demand from LRCLIB; synchronized timing is not available for this match."
            )
    elif lyrics_result.get("status") == "instrumental":
        st.info("LRCLIB marks this recording as instrumental.")
    elif lyrics_result.get("status") == "provider-error":
        st.warning(lyrics_result.get("message"))

    if track.get("sync_note") and not using_lrclib_sync:
        st.caption(track["sync_note"])

    render_song_background(repository, track)

    section("Song credits", "Who made this record")
    credits = track.get("credits")
    if not credits:
        credits = {
            "Catalog performers": ", ".join(
                track.get("performers") or [track["artist"]]
            ),
            "Album": track["album"],
            "Writing / production": "Not yet verified in the reviewed archive",
        }
        if track.get("featured_artists"):
            credits["Featured artists"] = ", ".join(track["featured_artists"])
    credit_columns = st.columns(min(3, len(credits)))
    for index, (label, value) in enumerate(credits.items()):
        credit_columns[index % len(credit_columns)].markdown(
            f'<div class="metric-card"><span>{safe(label)}</span><strong style="font-size:1.05rem">{safe(value)}</strong></div>',
            unsafe_allow_html=True,
        )

    destinations = [
        ("Open on YouTube ↗", track["youtube_url"]),
        (
            "Search lyrics on Genius ↗"
            if "/search?" in track["genius_url"]
            else "Open lyrics on Genius ↗",
            track["genius_url"],
        ),
    ]
    if lyrics_result.get("status") in {"matched", "instrumental"}:
        destinations.append(
            ("View LRCLIB source ↗", lyrics_result["provider_url"])
        )
    if track.get("apple_music_url"):
        destinations.append(("Open on Apple Music ↗", track["apple_music_url"]))
    link_columns = st.columns(len(destinations))
    for column, (label, url) in zip(link_columns, destinations):
        column.link_button(label, url, use_container_width=True)
    with st.expander("Album-story sources"):
        source_cards(repository, track.get("album_sources", []))
    st.info(
        "LRCLIB is a separate community lyrics provider. Threadline requests a match "
        "only when this song page opens, caches the response temporarily, attributes "
        "the source, and does not add the text to its reviewed archive. Lyrics rights "
        "remain with their writers and publishers."
    )


def render_connections(repository: ArchiveRepository, universe: dict) -> None:
    section(
        "Connected universe",
        "Follow the people, not an algorithm",
        "Each relationship links to another local universe. Synchronized catalogs are available even when their long-form story is still being reviewed.",
    )
    related = universe.get("related", [])
    if not related:
        st.info("No mapped connections are available yet.")
        return

    columns = st.columns(2)
    for index, relation in enumerate(related):
        target = repository.get_universe(relation["universe_id"])
        if not target:
            continue
        with columns[index % 2]:
            st.markdown(
                f'<div class="metric-card"><div class="eyebrow">{safe(target["kind"])}</div>'
                f'<strong>{safe(target["name"])}</strong>'
                f'<div class="connection-line">{safe(relation["relationship"])}</div></div>',
                unsafe_allow_html=True,
            )
            if st.button(f"Enter {target['name']}", key=f"connection-{universe['id']}-{target['id']}"):
                open_local_universe(target["id"])
                st.rerun()


def render_ask(repository: ArchiveRepository, universe: dict) -> None:
    section(
        "Grounded research guide",
        "Ask the reviewed archive",
        "Answers are extracted from reviewed passages. The system shows its evidence, labels interpretation, and abstains when support is weak.",
    )
    include_interpretations = st.toggle(
        "Include clearly labeled critical interpretations",
        value=False,
        help="Artist statements, documented facts, and reporting are included by default. Fan theories are never silently presented as fact.",
    )
    examples = {
        "tyler-the-creator": "Did Pharrell directly cause Flower Boy?",
        "odd-future": "How did Odd Future use the internet to build a following?",
        "syd": "What has Syd publicly said about learning production?",
        "the-internet": "How did Syd and Matt Martians work together?",
    }
    with st.form("archive-question-form"):
        question = st.text_input(
            "Your question",
            placeholder=examples.get(universe["id"], f"What connects {universe['name']} to this universe?"),
        )
        submitted = st.form_submit_button("Search the story")

    if not submitted:
        return

    engine = GroundedAnswerEngine(repository)
    answer = engine.answer(
        question,
        universe_id=universe["id"],
        include_interpretations=include_interpretations,
    )
    if answer.status == "invalid-input":
        st.warning(answer.text)
        return
    if answer.status == "insufficient-evidence":
        st.warning(answer.text)
    else:
        st.markdown(f'<div class="answer">{safe(answer.text)}</div>', unsafe_allow_html=True)

    left, right = st.columns(2)
    left.metric("Retrieval confidence", f"{answer.confidence:.0%}")
    right.metric("Evidence passages", len(answer.evidence))
    if answer.guardrail_note:
        st.markdown(f'<div class="guardrail">{safe(answer.guardrail_note)}</div>', unsafe_allow_html=True)

    if answer.evidence:
        st.subheader("Evidence trail")
        for evidence in answer.evidence:
            with st.expander(
                f"{evidence['title']} · {evidence['claim_type'].replace('-', ' ')}"
            ):
                st.write(evidence["text"])
                st.caption(
                    f"Passage confidence: {evidence['confidence']:.0%} · "
                    f"Matched: {', '.join(evidence['matched_terms'])}"
                )
    if answer.sources:
        st.subheader("Sources")
        for source in answer.sources:
            source_cards(repository, [source["id"]])


def render_live(universe: dict) -> None:
    section(
        "Separate live layer",
        "Upcoming concerts",
        "This information is fetched on request and never rewritten into the reviewed historical narrative.",
    )
    city = st.text_input(
        "Narrow by city (optional)",
        value=st.session_state.get("concert_city", ""),
        placeholder="Leave blank to see all incoming shows",
        key="concert_city",
    )
    with st.spinner("Loading incoming shows…"):
        result = load_live_events(
            universe["name"],
            city.strip(),
            bool(os.getenv("TICKETMASTER_API_KEY")),
        )
    st.markdown(
        f'<p><span class="status-live">LIVE · UPCOMING FIRST</span> · Checked {safe(result["checked_at"])}</p>',
        unsafe_allow_html=True,
    )
    if result["status"] == "ok" and result["events"]:
        st.success(result["message"])
        events = sorted(result["events"], key=lambda event: (event["date"], event["time"]))
        for event in events:
            location = ", ".join(part for part in [event["city"], event["region"]] if part)
            left, right = st.columns([4, 1])
            left.markdown(
                f'<div class="story-card"><div class="story-era">{safe(event["date"])} {safe(event["time"])}</div>'
                f'<h3>{safe(event["name"])}</h3><p>{safe(event["venue"])} · {safe(location)}</p>'
                f'<span class="claim">status: {safe(event["status"])}</span></div>',
                unsafe_allow_html=True,
            )
            right.link_button(
                "Tickets / details ↗",
                event["url"],
                use_container_width=True,
                type="primary",
            )
    else:
        st.info(result["message"])
        st.write("Continue directly to a ticket search:")
        ticket_columns = st.columns(2)
        ticket_columns[0].link_button(
            "Search Ticketmaster ↗",
            "https://www.ticketmaster.com/search?q=" + quote_plus(universe["name"]),
            use_container_width=True,
        )
        ticket_columns[1].link_button(
            "Search Bandsintown ↗",
            "https://www.bandsintown.com/search?q=" + quote_plus(universe["name"]),
            use_container_width=True,
        )
    st.caption(
        "Concert listings can change or be canceled. Always verify dates, venue details, "
        "and ticket status with the official event page before purchasing or traveling."
    )


def main() -> None:
    inject_styles()
    repository_revision = tuple(
        path.stat().st_mtime_ns if path.exists() else 0
        for path in REPOSITORY_DATA_PATHS
    )
    repository = load_repository(repository_revision)
    st.session_state.setdefault("page", "home")
    st.session_state.setdefault("universe_id", "tyler-the-creator")
    st.session_state.setdefault("view", "Overview")
    render_top_bar()

    if st.session_state.page == "home":
        render_home(repository)
        return

    if st.session_state.page == "library":
        st.sidebar.caption(
            "Apple Music XML metadata is processed for this session and is not added to the reviewed archive."
        )
        render_library(repository)
        return

    if st.session_state.page == "journey":
        render_tyler_journey(repository)
        return

    if st.session_state.page == "album":
        album_universe = repository.get_universe(
            st.session_state.get("universe_id", "")
        )
        selected_album_id = st.session_state.get("selected_album_id")
        selected_album = next(
            (
                item
                for item in (album_universe or {}).get("albums", [])
                if item["id"] == selected_album_id
            ),
            None,
        )
        if not album_universe or not selected_album:
            st.session_state.page = "universe"
            st.session_state.view = "Albums"
            st.rerun()
        st.sidebar.markdown(f"**{album_universe['name']}**")
        if album_universe.get("catalog_generated"):
            st.sidebar.caption(
                "Synchronized MusicBrainz + YouTube Music catalog · "
                "story context is reviewed separately"
            )
        else:
            st.sidebar.caption(
                f"Reviewed archive {repository.data['archive_version']} · "
                f"{repository.data['reviewed_at']}"
            )
        render_album_page(repository, album_universe, selected_album)
        return

    if st.session_state.page == "song":
        track = st.session_state.get("song")
        if not track:
            st.session_state.page = "home"
            st.rerun()
        track = refresh_song_record(repository, track)
        st.session_state.song = track
        if st.session_state.get("journey_guided_song"):
            render_journey_song_navigation(repository)
        render_song_page(repository, track)
        return

    universe = st.session_state.get("catalog_profile")
    if not universe:
        universe = repository.get_universe(st.session_state.universe_id)
    if not universe:
        st.session_state.page = "home"
        st.rerun()

    reviewed = universe.get("reviewed", True)
    detailed_catalog = bool(universe.get("catalog_generated")) and not reviewed
    if reviewed:
        views = ["Overview", "Story", "Albums", "Connections", "Ask the archive", "Live concerts"]
    elif detailed_catalog:
        views = ["Overview", "Albums", "Connections", "Live concerts"]
    else:
        views = ["Overview", "Discography", "Live concerts"]
    if st.session_state.view not in views:
        st.session_state.view = "Overview"
    st.sidebar.markdown(f"**{universe['name']}**")
    st.sidebar.radio("Explore", views, key="view")
    st.sidebar.markdown("---")
    if reviewed:
        st.sidebar.caption(
            f"Reviewed archive {repository.data['archive_version']} · {repository.data['reviewed_at']}"
        )
    elif detailed_catalog:
        st.sidebar.caption(
            "Synchronized MusicBrainz + YouTube Music catalog · story not yet reviewed"
        )
    else:
        st.sidebar.caption("Universal MusicBrainz catalog profile · story not yet reviewed")

    navigation_error = st.session_state.pop("navigation_error", None)
    if navigation_error:
        st.warning(navigation_error)
    render_header(universe)
    if reviewed:
        renderers = {
            "Overview": lambda: render_overview(repository, universe),
            "Story": lambda: render_story(repository, universe),
            "Albums": lambda: render_albums(repository, universe),
            "Connections": lambda: render_connections(repository, universe),
            "Ask the archive": lambda: render_ask(repository, universe),
            "Live concerts": lambda: render_live(universe),
        }
    elif detailed_catalog:
        renderers = {
            "Overview": lambda: render_catalog_overview(repository, universe),
            "Albums": lambda: render_albums(repository, universe),
            "Connections": lambda: render_connections(repository, universe),
            "Live concerts": lambda: render_live(universe),
        }
    else:
        renderers = {
            "Overview": lambda: render_catalog_overview(repository, universe),
            "Discography": lambda: render_catalog_discography(universe),
            "Live concerts": lambda: render_live(universe),
        }
    renderers[st.session_state.view]()


if __name__ == "__main__":
    main()
