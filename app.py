# --- Force IPv4 (Fix for WinError 10060 on networks with broken IPv6) ---
import socket
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    if family == 0:
        family = socket.AF_INET
    return orig_getaddrinfo(host, port, family, type, proto, flags)

orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = getaddrinfo_ipv4
# ------------------------------------------------------------------------

import streamlit as st
import pandas as pd
import difflib
import re
import random
import requests
import xml.etree.ElementTree as ET

try:
    from googleapiclient.discovery import build
    from youtube_transcript_api import YouTubeTranscriptApi
    from kiwipiepy import Kiwi
except ImportError as e:
    st.error(f"Libraries not installed: {e}. Please run `pip install -r requirements.txt`")
    st.stop()

import streamlit.components.v1 as components
from translations import LANGUAGES, LANG_TO_API, get_text

# Kiwi 형태소 분석기 초기화
@st.cache_resource
def get_kiwi():
    return Kiwi()

kiwi = get_kiwi()


# --- Removed MonkeyPatch (No longer needed with official API) ---

# 한국어기초사전 API
if "KRDICT_API_KEY" in st.secrets:
    KRDICT_API_KEY = st.secrets["KRDICT_API_KEY"]
else:
    # Fallback or Error (For now, let's keep the hardcoded one as a fallback for local testing convenience, 
    # but strictly it should be in secrets.toml. Let's force secrets for consistency with deployment best practices.)
    # However, to avoid immediate breakage for the user locally if they haven't updated secrets.toml yet:
    KRDICT_API_KEY = "BFCA7CF8A91CE6BE2C4B45D3C71188DA" # Default (Will be overridden by secrets)
    # Or better, just load it:
    # KRDICT_API_KEY = st.secrets["KRDICT_API_KEY"]


def get_word_definitions(word, lang_code="ko", max_results=3):
    """한국어기초사전 API로 단어 뜻 조회 - 여러 결과 반환"""
    results = []
    try:
        tokens = kiwi.tokenize(word)
        search_word = tokens[0].form if tokens else word
        
        url = "https://krdict.korean.go.kr/api/search"
        params = {"key": KRDICT_API_KEY, "q": search_word}
        
        if lang_code != "ko" and lang_code in LANG_TO_API:
            params["translated"] = "y"
            params["trans_lang"] = LANG_TO_API[lang_code]
        
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            root = ET.fromstring(response.text)
            items = root.findall(".//item")
            
            for item in items[:max_results]:
                word_elem = item.find("word")
                sense = item.find(".//sense")
                if sense is not None:
                    definition = sense.find("definition")
                    trans_word = sense.find(".//trans_word")
                    trans_dfn = sense.find(".//trans_dfn")
                    
                    result = {
                        "word": word_elem.text if word_elem is not None else word,
                        "definition": definition.text if definition is not None else "",
                        "translation": trans_word.text if trans_word is not None else "",
                        "trans_definition": trans_dfn.text if trans_dfn is not None else ""
                    }
                    results.append(result)
    except:
        pass
    return results

def analyze_wrong_morphemes(correct_word, user_word):
    """형태소 분석으로 정확히 틀린 부분 식별"""
    correct_tokens = kiwi.tokenize(correct_word)
    user_tokens = kiwi.tokenize(user_word) if user_word else []
    
    user_forms = {t.form for t in user_tokens}
    missing = [t.form for t in correct_tokens if t.form not in user_forms and not t.tag.startswith('J')]
    return missing

def generate_diff_html(correct, user_input):
    """디프 HTML 생성 (빨간색/초록색 표시)"""
    diff = difflib.ndiff(user_input, correct)
    diff_html = ""
    for s in diff:
        if s[0] == ' ':
            diff_html += s[2]
        elif s[0] == '-':
            diff_html += f"<span style='color:red; text-decoration:line-through;'>{s[2]}</span>"
        elif s[0] == '+':
            diff_html += f"<span style='color:green; font-weight:bold;'>{s[2]}</span>"
    return diff_html

st.set_page_config(page_title="K-Tube Dictation", layout="wide")

# Session State Initialization
defaults = {
    'history': [], 'vocabulary': [], 'selected_video': None, 'transcript_data': None,
    'search_results': [], 'should_autoplay': False, 'replay_count': 0,
    'current_blank_answers': [], 'current_masked_text': "", 'blank_generation_idx': -1,
    'ui_lang': "en", 'dict_search_result': None,
    'check_states': {} # Stores check status for each index: {index: {'checked': bool, 'user_input': str, 'result_data': ...}}
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

def t(key):
    return get_text(key, st.session_state.ui_lang)

st.title(t("app_title"))

# Sidebar
with st.sidebar:
    st.header(t("settings"))
    
    lang_options = list(LANGUAGES.keys())
    current_lang_idx = lang_options.index(st.session_state.ui_lang) if st.session_state.ui_lang in lang_options else 0
    selected_lang = st.selectbox(t("language"), options=lang_options, format_func=lambda x: LANGUAGES[x], index=current_lang_idx)
    if selected_lang != st.session_state.ui_lang:
        st.session_state.ui_lang = selected_lang
        st.rerun()
    
    difficulty = st.radio(t("difficulty"), [t("easy"), t("hard")])
    shuffle_order = st.checkbox(t("shuffle"), value=False)
    
    st.divider()
    st.markdown(f"### {t('stats')}")
    st.write(f"{t('total_logged')}: {len(st.session_state.history)}")
    st.write(f"📚 Vocabulary: {len(st.session_state.vocabulary)}")

    st.markdown("---")
    # Buy Me a Coffee Button (Subtle with Tooltip)
    st.link_button("☕ Buy me a coffee", "https://www.buymeacoffee.com/kyeranpang", help=t("buy_coffee_help"), use_container_width=True)
    
    # Feedback Button
    st.link_button(t("feedback_btn"), "https://docs.google.com/forms/d/e/1FAIpQLSelt5J37ezgnnq8n75oh2poGAVt34iJYc2wZypPTSDr69c9Kw/viewform", use_container_width=True)

# 메인 탭 UI (기록 탭 분리: 문장/단어)
tab_study, tab_sentences, tab_vocabulary = st.tabs([t("study"), "📝 Sentences", "📚 Vocabulary"])

def get_transcript(video_id):
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        transcript = transcript_list.find_transcript(['ko'])
        fetched = transcript.fetch()
        return [{'text': item.text, 'start': item.start, 'duration': item.duration} for item in fetched]
    except:
        return None

def display_dictionary_results(definitions, show_add_button=False, context=""):
    """사전 결과 표시 및 단어장 추가 버튼"""
    for i, defn in enumerate(definitions, 1):
        col_def, col_btn = st.columns([5, 1])
        with col_def:
            if st.session_state.ui_lang != "ko" and defn.get('trans_definition'):
                st.markdown(f"**{i}. {defn['word']}**: {defn['definition']}")
                st.caption(f"→ {defn['trans_definition']}")
            else:
                st.markdown(f"**{i}. {defn['word']}**: {defn['definition']}")
        
        if show_add_button:
            with col_btn:
                if st.button("⭐", key=f"add_vocab_{defn['word']}_{i}", help="Add to vocabulary"):
                    vocab_entry = {
                        "word": defn['word'],
                        "definition": defn['definition'],
                        "translation": defn.get('trans_definition', ''),
                        "context": context,
                        "date": pd.Timestamp.now().strftime("%Y-%m-%d")
                    }
                    st.session_state.vocabulary.append(vocab_entry)
                    st.success(f"✓ Added '{defn['word']}'")

with tab_study:
    st.subheader(t("study_mode"))
    
    # User Guide Expander
    with st.expander(t("user_guide_title"), expanded=True):
        st.markdown(t("user_guide_md"))

    with st.form("search_form", clear_on_submit=False):
        col1, col2 = st.columns([4, 1])
        with col1:
            search_query = st.text_input(t("search_youtube"), placeholder=t("search_placeholder"), key="search_input")
        with col2:
            search_btn = st.form_submit_button(t("search"), use_container_width=True)
            
    if search_btn and search_query:
        st.session_state.selected_video = None
        st.session_state.transcript_data = None
        st.session_state.last_search_query = search_query  # 검색어 저장
        with st.spinner(t("searching")):
            try:
                # Official API Search
                if "YOUTUBE_API_KEY" not in st.secrets:
                   st.error("⚠️ YouTube API Key is missing. Please add it to `.streamlit/secrets.toml`.")
                   st.stop()
                
                api_key = st.secrets["YOUTUBE_API_KEY"]
                youtube = build('youtube', 'v3', developerKey=api_key)
                
                # 1. Search Request (Cost: 100 quota)
                search_response = youtube.search().list(
                    q=search_query,
                    part='snippet',
                    type='video',
                    maxResults=10
                ).execute()
                
                # 2. Get Video IDs for Duration (Cost: 1 quota)
                video_ids = [item['id']['videoId'] for item in search_response.get('items', [])]
                
                durations = {}
                if video_ids:
                    vid_response = youtube.videos().list(
                        part="contentDetails",
                        id=",".join(video_ids)
                    ).execute()
                    
                    # ISO 8601 Duration Parser (Simple version)
                    def parse_duration(duration_str):
                        # Example: PT5M30S, PT1H, PT30S
                        # Fallback parsing (Manual regex)
                        match = re.search(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
                        if not match: return "N/A"
                        parts = match.groups()
                        h = parts[0] if parts[0] else "0"
                        m = parts[1] if parts[1] else "0"
                        s = parts[2] if parts[2] else "0"
                        
                        if int(h) > 0:
                            return f"{h}:{int(m):02d}:{int(s):02d}"
                        else:
                            return f"{m}:{int(s):02d}"

                    for item in vid_response.get('items', []):
                        durations[item['id']] = parse_duration(item['contentDetails']['duration'])

                # 3. Construct Results
                results = []
                for item in search_response.get('items', []):
                    vid_id = item['id']['videoId']
                    snippet = item['snippet']
                    results.append({
                        'id': vid_id,
                        'title': snippet['title'],
                        'thumbnails': [{'url': snippet['thumbnails']['high']['url']}], # Use high quality
                        'channel': {'name': snippet['channelTitle']},
                        'duration': durations.get(vid_id, "N/A"),
                        'publishedTime': snippet['publishedAt'][:10] # YYYY-MM-DD
                    })
                
                st.session_state.search_results = results
                
            except Exception as e:
                st.error(f"Search failed: {e}")
            
    if st.session_state.search_results:
        display_query = st.session_state.get('last_search_query', 'Previous Search')
        st.write(f"{t('results_for')}: {display_query}")
        
        if st.session_state.selected_video:
            if st.button(t("back_to_results")):
                st.session_state.selected_video = None
                st.session_state.transcript_data = None
                st.rerun()

        if not st.session_state.selected_video:
            for vid in st.session_state.search_results:
                with st.container():
                    c1, c2 = st.columns([3, 7])
                    with c1:
                        if vid.get('thumbnails'):
                            st.image(vid['thumbnails'][0]['url'], use_container_width=True)
                    with c2:
                        st.markdown(f"**{vid.get('title', 'No Title')}**")
                        st.caption(f"{vid.get('channel', {}).get('name', 'Unknown')} | {vid.get('duration') or 'N/A'}")
                        if st.button(t("study_this"), key=f"btn_{vid['id']}", use_container_width=True):
                            with st.spinner(t("checking_subtitles")):
                                transcript = get_transcript(vid['id'])
                                if transcript:
                                    if shuffle_order:
                                        random.shuffle(transcript)
                                    st.session_state.selected_video = vid
                                    st.session_state.transcript_data = transcript
                                    st.session_state.current_index = 0
                                    st.session_state.should_autoplay = False
                                    st.rerun()
                                else:
                                    st.error(t("no_korean_subtitles"))
                    st.divider()
                                
        else:
            st.divider()
            vid = st.session_state.selected_video
            st.success(t("study_start_msg"))
            st.markdown(f"### {t('now_studying')}: {vid['title']}")
            
            transcript_data = st.session_state.transcript_data
            current_idx = st.session_state.get('current_index', 0)
            
            if current_idx < 0:
                current_idx = 0
                st.session_state.current_index = 0
            
            if current_idx >= len(transcript_data):
                st.success(t("completed_all"))
                if st.button(t("restart")):
                    st.session_state.current_index = 0
                    st.rerun()
            else:
                curr_item = transcript_data[current_idx]
                start_time = curr_item['start']
                end_time = start_time + curr_item['duration']
                original_text = curr_item['text']
                
                play_start = max(0, start_time - 1)
                play_end = end_time + 1
                
                autoplay_param = "1" if st.session_state.should_autoplay else "0"
                cache_bust = st.session_state.replay_count
                video_url = f"https://www.youtube.com/embed/{vid['id']}?start={int(play_start)}&end={int(play_end)}&autoplay={autoplay_param}&cc_load_policy=3&iv_load_policy=3&rel=0&modestbranding=1&cb={cache_bust}"
                components.iframe(video_url, height=400)
                st.caption(f"{t('segment')}: {int(start_time)}s - {int(end_time)}s ({t('margin')}) | {t('index')}: {current_idx + 1}/{len(transcript_data)}")
                
                st.session_state.should_autoplay = False
                
                c_prev, c_repeat, c_next = st.columns(3)
                with c_prev:
                    if st.button(t("prev")):
                        if current_idx > 0:
                            st.session_state.current_index -= 1
                            st.session_state.should_autoplay = True
                            st.rerun()
                with c_repeat:
                    play_label = t("play") if current_idx == 0 else t("replay")
                    if st.button(play_label):
                        st.session_state.should_autoplay = True
                        st.session_state.replay_count += 1
                        st.rerun()
                with c_next:
                    if st.button(t("next")):
                        if current_idx < len(transcript_data) - 1:
                            st.session_state.current_index += 1
                            st.session_state.should_autoplay = True
                            st.rerun()

                with st.form(f"answer_form_{current_idx}", clear_on_submit=False):
                    words = original_text.split()
                    blank_answers = []
                    
                    if difficulty == t("easy"):
                        if st.session_state.blank_generation_idx != current_idx:
                            candidate_words = [w for w in words if len(w) >= 2]
                            num_blanks = min(2, len(candidate_words))
                            blank_words = random.sample(candidate_words, num_blanks) if num_blanks > 0 else []
                            
                            masked_words = []
                            actual_blanks = []
                            for w in words:
                                if w in blank_words and w not in actual_blanks:
                                    masked_words.append("____")
                                    actual_blanks.append(w)
                                else:
                                    masked_words.append(w)
                            
                            st.session_state.current_blank_answers = actual_blanks
                            st.session_state.current_masked_text = " ".join(masked_words)
                            st.session_state.blank_generation_idx = current_idx
                        
                        blank_answers = st.session_state.current_blank_answers
                        masked_text = st.session_state.current_masked_text
                        
                        st.info(f"{t('fill_blanks')} ({len(blank_answers)}{t('blanks_count')}): {masked_text}")
                        user_input = st.text_input(t("enter_blanks"), key=f"input_{current_idx}")
                    else:
                        user_input = st.text_input(t("type_what_you_hear"), key=f"input_{current_idx}")
                    
                    submit_btn = st.form_submit_button(t("check_answer"))
                
                # State Persistence Logic
                if submit_btn:
                    st.session_state.check_states[current_idx] = {
                        'checked': True,
                        'user_input': user_input
                    }
                
                # Retrieve state
                current_state = st.session_state.check_states.get(current_idx, {})
                
                if current_state.get('checked'):
                    # Use persisted input if available
                    if not submit_btn: # If it's a rerun (e.g. star button clicked), use stored input
                         user_input = current_state['user_input']

                    def normalize_text(text):
                        return re.sub(r'[.,!?;:"\'\-…]', '', text).strip()
                    
                    wrong_words_list = []
                    diff_html = ""
                    
                    if difficulty == t("easy"):
                        user_words = [normalize_text(w) for w in user_input.strip().split()]
                        normalized_answers = [normalize_text(w) for w in blank_answers]
                        
                        if user_words == normalized_answers:
                            st.success(t("correct"))
                            is_correct = True
                        else:
                            st.error(t("incorrect"))
                            
                            # Phase 5: Easy 모드에서도 디프 표시
                            for i, (correct, user) in enumerate(zip(normalized_answers, user_words + [''] * len(normalized_answers))):
                                if correct != user:
                                    diff_html += generate_diff_html(correct, user) + " "
                                    missing = analyze_wrong_morphemes(correct, user)
                                    wrong_words_list.extend(missing if missing else [correct])
                                else:
                                    diff_html += f"<span style='color:gray;'>{correct}</span> "
                            
                            st.markdown(f"**{t('comparison')}:** {diff_html}", unsafe_allow_html=True)
                            st.markdown(f"**{t('correct_blanks')}:** {' '.join(blank_answers)}")
                            st.markdown(f"**{t('full_sentence')}:** {original_text}")
                            
                            if wrong_words_list:
                                st.markdown("---")
                                st.markdown(f"**{t('dictionary')}:**")
                                displayed = set()
                                for word in wrong_words_list[:3]:
                                    if word in displayed:
                                        continue
                                    displayed.add(word)
                                    definitions = get_word_definitions(word, st.session_state.ui_lang, max_results=3)
                                    if definitions:
                                        display_dictionary_results(definitions, show_add_button=True, context=original_text)
                            
                            is_correct = False
                    else:
                        if normalize_text(user_input) == normalize_text(original_text):
                            st.success(t("correct"))
                            is_correct = True
                        else:
                            st.error(t("incorrect"))
                            diff_html = generate_diff_html(original_text, user_input)
                            st.markdown(f"**{t('comparison')}:** {diff_html}", unsafe_allow_html=True)
                            st.markdown(f"**{t('full_sentence')}:** {original_text}")
                            is_correct = False
                        
                    # History 저장 (고정 영어 키) - Only save if just submitted (prevent duplicate on rerun)
                    if submit_btn:
                        record = {
                            "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                            "video_title": vid['title'],
                            "timestamp": f"{int(start_time//60)}:{int(start_time%60):02d}",
                            "original_text": original_text,
                            "user_input": user_input,
                            "is_correct": "✓" if is_correct else "✗",
                            "blank_words": ", ".join(blank_answers) if blank_answers else "-",
                            "wrong_words": ", ".join(wrong_words_list[:3]) if wrong_words_list else "-",
                            "diff_html": diff_html if not is_correct else ""
                        }
                        st.session_state.history.append(record)
                
                # Phase 5: 수동 사전 검색 기능
                st.markdown("---")
                st.markdown(f"### 📖 {t('dictionary')}")
                with st.form("dict_search_form", clear_on_submit=False):
                    dict_col1, dict_col2 = st.columns([4, 1])
                    with dict_col1:
                        dict_query = st.text_input("Search word:", placeholder="Enter any Korean word", key="dict_input")
                    with dict_col2:
                        dict_btn = st.form_submit_button("🔍", use_container_width=True)
                
                if dict_btn and dict_query:
                    definitions = get_word_definitions(dict_query, st.session_state.ui_lang, max_results=3)
                    if definitions:
                        display_dictionary_results(definitions, show_add_button=True, context=original_text if 'original_text' in dir() else "")
                    else:
                        st.warning("No results found.")

# Sentences Tab (Phase 5: 기록 탭 분리)
with tab_sentences:
    st.subheader("📝 Sentence History")
    if st.session_state.history:
        total = len(st.session_state.history)
        correct_count = sum(1 for x in st.session_state.history if x.get("is_correct") == "✓")
        accuracy = (correct_count / total) * 100 if total > 0 else 0
        
        col1, col2 = st.columns(2)
        col1.metric(t("total_sentences"), total)
        col2.metric(t("accuracy"), f"{accuracy:.1f}%")
        
        # 컬럼 표시 (고정 영어 키, 번역 표시)
        display_cols = ["date", "video_title", "original_text", "user_input", "is_correct", "blank_words", "wrong_words"]
        df = pd.DataFrame(st.session_state.history)[display_cols]
        df.columns = [t(col) for col in display_cols]
        st.dataframe(df, use_container_width=True)
        
        # 디프 HTML 표시 (상세 보기)
        with st.expander("View detailed comparisons"):
            for i, record in enumerate(st.session_state.history):
                if record.get("diff_html"):
                    st.markdown(f"**#{i+1}:** {record['diff_html']}", unsafe_allow_html=True)
        
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(t("download_csv"), csv, "dictation_history.csv", "text/csv", key='download-sentences-csv')
    else:
        st.info(t("no_history"))

# Vocabulary Tab (Phase 5: 단어장)
with tab_vocabulary:
    st.subheader("📚 My Vocabulary")
    if st.session_state.vocabulary:
        st.metric("Total Words", len(st.session_state.vocabulary))
        
        vocab_df = pd.DataFrame(st.session_state.vocabulary)
        st.dataframe(vocab_df, use_container_width=True)
        
        vocab_csv = vocab_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Vocabulary CSV", vocab_csv, "vocabulary.csv", "text/csv", key='download-vocab-csv')
        
        if st.button("🗑️ Clear All Vocabulary"):
            st.session_state.vocabulary = []
            st.rerun()
    else:
        st.info("No words saved yet. Use the ⭐ button in dictionary results to add words!")
