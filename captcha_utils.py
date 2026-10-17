# captcha_utils.py
import random
import tempfile
import os
import base64
import streamlit as st
import streamlit.components.v1 as components

def generate_audio_b64(text: str) -> str:
    """Generates base64 WAV audio for text using Windows SAPI voice."""
    try:
        import win32com.client
        temp_dir = tempfile.gettempdir()
        wav_path = os.path.join(temp_dir, "captcha_speech.wav")
        
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        # 3 = SSFMCreateForWrite
        stream.Open(wav_path, 3, False)
        speaker.AudioOutputStream = stream
        speaker.Speak(text)
        stream.Close()
        
        with open(wav_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode('utf-8')
    except Exception as e:
        print("Error generating CAPTCHA audio:", e)
        return ""

def generate_captcha():
    """Generates a math challenge for CAPTCHA verification."""
    num1 = random.randint(1, 12)
    num2 = random.randint(1, 12)
    operator = random.choice(["+", "-"])
    
    if operator == "+":
        answer = num1 + num2
        speech_op = "plus"
    else:
        # Ensure positive result
        if num1 < num2:
            num1, num2 = num2, num1
        answer = num1 - num2
        speech_op = "minus"
        
    st.session_state["captcha_question"] = f"{num1} {operator} {num2} = ?"
    st.session_state["captcha_speech_text"] = f"What is {num1} {speech_op} {num2}?"
    st.session_state["captcha_answer"] = answer
    st.session_state["captcha_solved"] = False
    st.session_state["captcha_version"] = st.session_state.get("captcha_version", 0) + 1
    st.session_state["captcha_input_value"] = ""
    
    # Pre-generate base64 audio
    speech_text = st.session_state["captcha_speech_text"]
    st.session_state["captcha_audio_b64"] = generate_audio_b64(speech_text)

def render_captcha():
    """Renders CAPTCHA UI with reload & audio support, returning True if solved successfully."""
    if "captcha_question" not in st.session_state or "captcha_answer" not in st.session_state:
        generate_captcha()

    q_text = st.session_state.get("captcha_question", "")
    st.markdown(
        "<div style='margin-bottom: 4px;'><label style='font-size: 14px; font-weight: 600;'>🔒 CAPTCHA <span style='color:red;'>*</span> :</label></div>",
        unsafe_allow_html=True
    )
    col_text, col_input, col_btn, _ = st.columns([1.0, 1.1, 0.7, 1.7], gap="small")
    
    with col_text:
        st.markdown(
            f"<div style='padding-top: 6px;'><span style='font-size: 14px; white-space: nowrap;'>What is <b style='color: #0066cc; font-weight: bold; font-size: 16px;'>{q_text}</b></span></div>",
            unsafe_allow_html=True
        )
    
    captcha_version = st.session_state.get("captcha_version", 0)
    with col_input:
        captcha_input = st.text_input(
            f"What is {q_text}",
            key=f"captcha_widget_{captcha_version}",
            max_chars=5,
            label_visibility="collapsed",
            placeholder="Enter answer"
        )
        st.session_state["captcha_input_value"] = captcha_input

    with col_btn:
        if st.button("🔄 Reload", key="reload_captcha_btn", help="Generate a new security challenge"):
            generate_captcha()
            st.rerun()

    # Interactive Audio Component rendered right below CAPTCHA input
    audio_b64 = st.session_state.get("captcha_audio_b64", "")
    if audio_b64:
        audio_html = f"""
        <div style="font-family: Arial, sans-serif; display: flex; align-items: center; gap: 10px; margin-top: 2px;">
            <button onclick="var a=document.getElementById('captcha_audio'); if(a){{ a.currentTime=0; a.play(); }}" style="
                background-color: #27ae60;
                color: white;
                border: none;
                padding: 6px 14px;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
                font-size: 13px;
                white-space: nowrap;
                height: 36px;
            ">🔊 Listen</button>
            <audio id="captcha_audio" controls src="data:audio/wav;base64,{audio_b64}" style="width: 100%; height: 36px;"></audio>
        </div>
        """
        components.html(audio_html, height=48)

    if captcha_input and captcha_input.strip():
        try:
            if int(captcha_input.strip()) == st.session_state["captcha_answer"]:
                st.session_state["captcha_solved"] = True
                return True
        except ValueError:
            pass
            
    st.session_state["captcha_solved"] = False
    return False





