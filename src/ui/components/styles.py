import streamlit as st

def inject_premium_css():
    """Injects custom CSS for a premium, modern dashboard look."""
    st.markdown(
        """
    <style>
        /* Main Layout */
        .stApp {
            background-color: #0a0a0a;
            color: #ededed;
            font-family: 'Inter', sans-serif;
        }

        /* Headers & Text */
        h1, h2, h3 {
            color: #ffffff !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em;
        }

        /* Sidebar Styling */
        [data-testid="stSidebar"] {
            background-color: #121212 !important;
            border-right: 1px solid rgba(255,255,255,0.05);
        }

        /* Buttons */
        .stButton>button {
            background: linear-gradient(135deg, #8A05BE 0%, #4338ca 100%);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 0.5rem 1rem;
            font-weight: 500;
            transition: all 0.3s ease;
        }
        .stButton>button:hover {
            opacity: 0.9;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(138,5,190,0.3);
        }

        /* Dataframes/Tables */
        [data-testid="stDataFrame"] {
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
        }

        /* File Uploader */
        [data-testid="stFileUploader"] {
            border: 1px dashed rgba(138,5,190,0.4);
            border-radius: 8px;
            background-color: rgba(255,255,255,0.02);
        }
    </style>
    """,
        unsafe_allow_html=True,
    )
