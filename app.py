import streamlit as st
from google import genai
from google.genai import types
import os, re, io
from docx import Document
from docx.shared import Pt, Inches
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from datetime import datetime

# ======================================================
# 1. 시스템 상수 및 API 설정
# ======================================================

MODEL_NAME = "gemini-2.5-flash"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")

st.set_page_config(
    page_title="메디푸드 분석 시스템",
    layout="wide",
    page_icon="🔬"
)

DISEASE_LIST = [
    "고혈압", "당뇨(1형/2형)", "고지혈증", "신장질환(CKD)", "투석 중",
    "간경화/지방간", "위염/위궤양", "역류성 식도염",
    "크론병/궤양성대장염", "갑상선 질환", "통풍",
    "골다공증", "심부전", "암 관리", "빈혈", "비만"
]

# ======================================================
# 2. Word(DOCX) 생성 엔진 (고정 레이아웃)
# ======================================================

def set_korean_font(run):
    run.font.name = '맑은 고딕'
    r = run._element
    rFonts = r.get_or_add_rPr().get_or_add_rFonts()
    rFonts.set(qn('w:eastAsia'), '맑은 고딕')

def create_docx_report(content: str):
    doc = Document()

    style = doc.styles['Normal']
    style.font.name = '맑은 고딕'
    style.font.size = Pt(10)
    style._element.get_or_add_rPr().get_or_add_rFonts().set(
        qn('w:eastAsia'), '맑은 고딕'
    )

    title = doc.add_heading('메디푸드 분석 리포트', 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    lines = content.split('\n')
    table_data = []
    is_table = False

    def flush_table():
        nonlocal table_data
        if not table_data:
            return

        table = doc.add_table(
            rows=len(table_data),
            cols=len(table_data[0])
        )
        table.style = 'Table Grid'
        table.autofit = False

        num_cols = len(table_data[0])
        total_width = 7.0
        col_width = total_width / num_cols

        for i, row in enumerate(table_data):
            for j, cell_text in enumerate(row):
                cell = table.cell(i, j)
                cell.width = Inches(col_width)

                p = cell.paragraphs[0]
                run = p.add_run(cell_text)
                set_korean_font(run)

                if i == 0 or j == 0:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                else:
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT

        doc.add_paragraph()
        table_data = []

    for line in lines:
        if re.search(r'\|.*\|', line):
            is_table = True
            row = [
                re.sub(r'\*\*', '', c.strip())
                for c in line.split('|')
                if c.strip() and not set(c.strip()).issubset({'-', ':', '|'})
            ]
            if row:
                table_data.append(row)
        else:
            if is_table:
                flush_table()
                is_table = False

            clean_line = re.sub(r'[\*\#]', '', line).strip()
            if clean_line:
                p = doc.add_paragraph()
                run = p.add_run(clean_line)
                set_korean_font(run)

    # 🔒 문서 끝이 표로 끝나는 경우 대비
    if is_table:
        flush_table()

    return doc

# ======================================================
# 3. 세션 관리
# ======================================================

if "session_id" not in st.session_state:
    st.session_state.session_id = 0

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = ""

def reset_system():
    st.session_state.analysis_result = ""
    st.session_state.session_id += 1
    st.rerun()

def shutdown_app():
    st.warning("시스템을 종료합니다.")
    st.stop()

# ======================================================
# 4. UI 레이아웃
# ======================================================

st.title("🔬 메디푸드 분석 시스템")

with st.sidebar:
    st.header("⚙️ 시스템 관리")

    if st.button("🔄 새 상담 시작 (리셋)"):
        reset_system()

    st.success("API Key 자동 인증 활성화")

    st.divider()
    st.header("📋 데이터 입력")

    s_id = st.session_state.session_id

    age = st.number_input(
        "나이",
        min_value=1,
        max_value=120,
        value=50,
        key=f"age_{s_id}"
    )

    gender = st.radio(
        "성별",
        ["남성", "여성"],
        key=f"gen_{s_id}"
    )

    disease = st.multiselect(
        "기저질환",
        DISEASE_LIST,
        key=f"dis_{s_id}"
    )

    medication = st.text_input(
        "복용 중인 약물",
        key=f"med_{s_id}"
    )

    st.divider()

    if st.button("🔴 시스템 종료"):
        shutdown_app()

symptom = st.text_area(
    "현재 증상 및 상세 특징",
    height=150,
    key=f"sym_{s_id}"
)

# ======================================================
# 5. 분석 실행
# ======================================================

if st.button("🚀 정밀 분석 및 식단표 생성"):
    if not symptom:
        st.warning("증상을 입력해 주세요.")
    else:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)

            prompt = f"""
[Role]
당신은 임상영양 기반 '메디푸드 분석 시스템'입니다.

[Instruction]
- 약초 및 한방 재료 제외
- 30일 식단표는 반드시 주차별 Markdown Table로 작성
- 주차별 식단표 이후 주의사항 포함

[Format Rule]
- 표는 |---| Markdown 형식만 사용
- 제목 → 설명 → 표 → 주의사항 순서

[User Data]
나이: {age}
성별: {gender}
기저질환: {', '.join(disease)}
복용 약물: {medication}
증상: {symptom}
"""

            with st.spinner("AI가 메디푸드 리포트를 생성 중입니다..."):
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt
                )
                st.session_state.analysis_result = response.text

        except Exception as e:
            st.error(f"실행 오류: {e}")

# ======================================================
# 6. 결과 출력 및 다운로드
# ======================================================

if st.session_state.analysis_result:
    st.divider()

    col_l, col_r = st.columns([8, 2])

    with col_l:
        st.subheader("📋 메디푸드 정밀 분석 결과")

    with col_r:
        doc = create_docx_report(st.session_state.analysis_result)
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        st.download_button(
            label="📥 Word 리포트 저장",
            data=buffer,
            file_name=f"medifood_report_{datetime.now().strftime('%Y%m%d')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    st.markdown(st.session_state.analysis_result)

