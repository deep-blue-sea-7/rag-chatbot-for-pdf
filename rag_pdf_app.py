import streamlit as st
import os
import tempfile

from langchain_openai import OpenAIEmbeddings
from langchain_openai import ChatOpenAI
from langchain_astradb import AstraDBVectorStore
from langchain.schema.runnable import RunnableMap
from langchain.prompts import ChatPromptTemplate
from langchain.callbacks.base import BaseCallbackHandler
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader

# Streaming call back handler for responses
class StreamHandler(BaseCallbackHandler):
    def __init__(self, container, initial_text=""):
        self.container = container
        self.text = initial_text

    def on_llm_new_token(self, token: str, **kwargs):
        self.text += token
        self.container.markdown(self.text + "▌")

# Function for Vectorizing uploaded data into Astra DB
def vectorize_text(uploaded_file, vector_store):
    if uploaded_file is not None:
        
        # Write to temporary file
        temp_dir = tempfile.TemporaryDirectory()
        file = uploaded_file
        temp_filepath = os.path.join(temp_dir.name, file.name)
        with open(temp_filepath, 'wb') as f:
            f.write(file.getvalue())

        # Load the PDF
        docs = []
        loader = PyPDFLoader(temp_filepath)
        docs.extend(loader.load())

        # Create the text splitter
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size = 1500,
            chunk_overlap  = 100
        )

        # Vectorize the PDF and load it into the Astra DB Vector Store
        pages = text_splitter.split_documents(docs)
        vector_store.add_documents(pages)  
        st.info(f"{len(pages)} pages loaded.")

# Cache prompt for future runs
@st.cache_data()
def load_prompt():
    template = """You're a helpful AI assistent tasked to answer the user's questions.
You're friendly and you answer extensively with multiple sentences. You prefer to use bulletpoints to summarize.

CONTEXT:
{context}

QUESTION:
{question}

YOUR ANSWER:"""
    return ChatPromptTemplate.from_messages([("system", template)])
prompt = load_prompt()

# Draw a title and some markdown
st.title("Your Personal Efficiency Booster")
st.markdown("""Your personal assistant answers your questions and lets you upload PDF documents
            as additional sources of specialized information, and makes them available to be searched.  """)
st.markdown("***")

st.title("To Use This Chat and PDF Assistant")
st.markdown("""1. Please sign up for OpenAI and create an API Key \n 2. Create a free account with Astra DB 
            and get the API Endpoint and Token. \n 3. Enter the OpenAI API Key, AstraDB API Endpoint and Token 
            in the fields in the left sidebar. \n\nOnce your enter the three elements, the chat box  and the upload feature willl be unlocked.  """)
st.markdown("***")

# Add field inputs for th API Keys in the sidebar
with st.sidebar:
    openai_api_key = st.text_input('OpenAI API Key 👇', type='password', disabled=False)
    astra_api_endpoint = st.text_input('Astra API Endpoint 👇', type='password', disabled=False)
    astra_token = st.text_input('Astra token 👇', type='password', disabled=False)
    st.markdown("***")

# Cache OpenAI Chat Model for future runs
@st.cache_resource()
def load_chat_model():
    return ChatOpenAI(
        temperature=0.3,
        model='gpt-3.5-turbo',
        streaming=True,
        verbose=True,
        openai_api_key=openai_api_key
    )

# Cache the Astra DB Vector Store for future runs
@st.cache_resource(show_spinner='Connecting to Astra')
def load_vector_store():
    # Connect to the Vector Store
    vector_store = AstraDBVectorStore(
        embedding=OpenAIEmbeddings(openai_api_key=openai_api_key),
        collection_name="my_store",
        api_endpoint=astra_api_endpoint,
        token=astra_token
    )
    return vector_store

# Cache the Retriever for future runs
@st.cache_resource(show_spinner='Getting retriever')
def load_retriever():
    # Get the retriever for the Chat Model
    retriever = vector_store.as_retriever(
        search_kwargs={"k": 5}
    )
    return retriever

# Get the API Key and execute the calls
if len(openai_api_key) > 0:
    chat_model = load_chat_model()

if len(openai_api_key) > 0 and len(astra_api_endpoint) > 0 and len(astra_token) > 0:
    vector_store = load_vector_store()
    retriever = load_retriever()


# Start with empty messages, stored in session state
if 'messages' not in st.session_state:
    st.session_state.messages = []

# Include the upload form for new data to be Vectorized. Make sure all keys and tokens are provided.
with st.sidebar:
    with st.form('upload'):
        uploaded_file = st.file_uploader('Upload a document for additional context', type=['pdf'], disabled=not(openai_api_key and astra_api_endpoint and astra_token))
        submitted = st.form_submit_button('Save to Astra DB', disabled=not(openai_api_key and astra_api_endpoint and astra_token))
        if submitted:
            vectorize_text(uploaded_file, vector_store)

# Draw all messages, both user and bot so far (every time the app reruns)
for message in st.session_state.messages:
    st.chat_message(message['role']).markdown(message['content'])

# Draw the chat input box
if question := st.chat_input("What can I help you with today", disabled=not(openai_api_key and astra_api_endpoint and astra_token)):
    
    if len(openai_api_key) == 0:
        st.warning('Please enter your OpenAI API key!', icon='⚠')
        
    else:
        # Store the user's question in a session object for redrawing next time
        st.session_state.messages.append({"role": "human", "content": question})

        # Draw the user's question
        with st.chat_message('human'):
            st.markdown(question)

        # UI placeholder to start filling with the agent response
        with st.chat_message('assistant'):
            response_placeholder = st.empty()

        # Generate the answer by calling OpenAI's Chat Model
        inputs = RunnableMap({
            'context': lambda x: retriever.get_relevant_documents(x['question']),
            'question': lambda x: x['question']
        })
        chain = inputs | prompt | chat_model
        response = chain.invoke({'question': question}, config={'callbacks': [StreamHandler(response_placeholder)]})
        answer = response.content

        # Store the bot's answer in a session object for redrawing next time
        st.session_state.messages.append({"role": "ai", "content": answer})

        # Write the final answer without the cursor
        response_placeholder.markdown(answer)