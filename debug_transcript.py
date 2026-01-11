from youtube_transcript_api import YouTubeTranscriptApi
import sys

# Video ID for "재재보다 케이팝 잘 아는 헐리웃 배우 실존 |🎙The MMTG SHOW"
# Based on search, it's likely this one or similar. 
# Let's try a few known MMTG video IDs or just a generic one if that fails.
# I'll try to find the ID for the specific video the user mentioned if possible, 
# but for now I'll use a placeholder or ask the user.
# Actually, I'll make the script accept an ID.

def test_transcript(video_id):
    print(f"Testing subtitle fetch for Video ID: {video_id}")
    try:
        # Instantiate the API class
        api = YouTubeTranscriptApi()
        
        # Use .list() instead of .list_transcripts()
        transcript_list = api.list(video_id)
        
        print("Available transcripts:")
        for t in transcript_list:
            print(f" - Language: {t.language} ({t.language_code}) | Generated: {t.is_generated} | Translatable: {t.is_translatable}")
            
        # Try fetching 'ko' specifically
        try:
            print("\nAttempting to fetch 'ko' transcript...")
            t = transcript_list.find_transcript(['ko'])
            data = t.fetch()
            print(f"Successfully fetched {len(data)} lines of Korean subtitles.")
            print(f"First line: {data[0]}")
        except Exception as e:
            print(f"Failed to fetch 'ko' specific transcript: {e}")

    except Exception as e:
        print(f"Fatal error listing transcripts: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        vid = sys.argv[1]
    else:
        # Default known MMTG video ID if none provided
        # I'll blindly guess/find one, or use a very popular one?
        # Let's use a very standard video ID that definitely has KR subs as a control 
        # AND the user's case if I can find it. 
        # For now, I'll default to a known working video ID locally to test the library.
        # Gangnam Style: 9bZkp7q19f0 (Has many subs? Maybe not clean ones).
        # Let's use the one from the MMTG channel if we can find it. 
        # Search query showed: "재재보다 케이팝 잘 아는 헐리웃 배우 실존"
        # Since I can't browse easily to get the ID right now without a subagent, 
        # I'll rely on the user or the app's output. 
        # BETTER IDEA: Use the debug script to SEARCH first? No, the library doesn't search.
        # I'll use a known video ID that definitely has Korean subs: 'jY8hV59vX1M' (Recent MMTG video potentially)
        # SOrry, can't guess. I'll use a SAFE fallback: 'gMaB-fG4u4g' (IU Palette) - usually has subs.
        # OOOOH, the user's video: "재재보다 케이팝 잘 아는 헐리웃 배우 실존" -> let's try to search via my search tool quickly?
        # Actually, I'll just write the script to accept an arg and I'll run it with a known ID.
        vid = "gMaB-fG4u4g" # Generic fallback
    
    test_transcript(vid)

    print("\n--- Debug Info ---")
    import youtube_transcript_api
    print(f"Module file: {youtube_transcript_api.__file__}")
    print(f"Version: {getattr(youtube_transcript_api, '__version__', 'unknown')}")
    print(f"Dir(YouTubeTranscriptApi): {dir(YouTubeTranscriptApi)}")
    
    print("\n--- Source Code of _api.py ---")
    import os
    try:
        api_path = os.path.join(os.path.dirname(youtube_transcript_api.__file__), '_api.py')
        with open(api_path, 'r') as f:
            print(f.read())
    except Exception as e:
        print(f"Could not read _api.py: {e}")



