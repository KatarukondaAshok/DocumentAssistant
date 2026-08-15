"""
rag.py
------
The RAG (Retrieval-Augmented Generation) pipeline.

Flow: Load -> Chunk -> Embed -> Store (ChromaDB) -> Retrieve -> Generate

Each uploaded document gets its own Chroma collection named
"user{user_id}_doc{document_id}". This keeps documents isolated per user
and makes deletion trivial (drop the collection).
"""
import os
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

from config import (
    CHROMA_DIR, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP, TOP_K,
    LLM_PROVIDER, OPENAI_API_KEY, OPENAI_MODEL, OLLAMA_MODEL, OLLAMA_BASE_URL,
)
from utils import logger

# Some Windows machines hit a CUDA/PTX JIT compile crash when Ollama tries to
# use the GPU. Forcing CPU-only avoids that entirely; llama3.2 (3B) is small
# enough to run acceptably on CPU.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("OLLAMA_NUM_GPU", "0")

# Embeddings model is loaded once and reused (expensive to reload per request)
_embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def _get_llm():
    """Returns a chat LLM based on the configured provider.
    Swappable: OpenAI for speed/quality, Ollama for a free local model."""
    if LLM_PROVIDER == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0)
    else:
        from langchain_openai import ChatOpenAI
        if not OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to your .env file, "
                "or set LLM_PROVIDER=ollama to use a local model instead."
            )
        return ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0)


def _load_document(filepath: str):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        loader = PyPDFLoader(filepath)
    elif ext == ".docx":
        loader = Docx2txtLoader(filepath)
    elif ext == ".txt":
        loader = TextLoader(filepath, encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file extension: {ext}")
    return loader.load()


def collection_name_for(user_id: int, document_id: int) -> str:
    return f"user{user_id}_doc{document_id}"


def ingest_document(filepath: str, user_id: int, document_id: int) -> int:
    """Loads a document, splits it into chunks, embeds each chunk, and
    stores the vectors in a dedicated ChromaDB collection.
    Returns the number of chunks created."""
    raw_docs = _load_document(filepath)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(raw_docs)

    collection = collection_name_for(user_id, document_id)
    Chroma.from_documents(
        documents=chunks,
        embedding=_embeddings,
        collection_name=collection,
        persist_directory=CHROMA_DIR,
    )
    logger.info(f"Ingested {len(chunks)} chunks into collection '{collection}'")
    return len(chunks)


def delete_document_vectors(user_id: int, document_id: int):
    collection = collection_name_for(user_id, document_id)
    try:
        store = Chroma(collection_name=collection, embedding_function=_embeddings, persist_directory=CHROMA_DIR)
        store.delete_collection()
    except Exception as e:
        logger.warning(f"Could not delete collection {collection}: {e}")


STRICT_QA_PROMPT = """You are a document assistant. Answer the QUESTION using ONLY the
CONTEXT below, which was retrieved from the user's uploaded document(s).

Rules:
- If the answer is not contained in the CONTEXT, reply exactly: "I don't have enough information in the uploaded document(s) to answer that."
- Do not use outside knowledge. Do not make anything up.
- Be concise and cite which part of the document supports your answer where possible.

CONTEXT:
{context}

QUESTION: {question}

ANSWER:"""

SUMMARY_PROMPT = """Summarize the following document content in a clear, well-structured way
(use short paragraphs or bullet points). Only use the information given below.

CONTENT:
{context}

SUMMARY:"""


def _retrieve(collections: list[str], query: str, k: int = TOP_K):
    """Searches one or more Chroma collections and returns the top-k
    (document, score) pairs merged and sorted by relevance."""
    results = []
    for name in collections:
        try:
            store = Chroma(collection_name=name, embedding_function=_embeddings, persist_directory=CHROMA_DIR)
            hits = store.similarity_search_with_relevance_scores(query, k=k)
            results.extend(hits)
        except Exception as e:
            logger.warning(f"Search failed for collection {name}: {e}")
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:k]


def answer_question(collections: list[str], question: str) -> tuple[str, list[str]]:
    """Runs semantic search + LLM generation, constrained to retrieved context.
    Returns (answer_text, list_of_source_snippets)."""
    hits = _retrieve(collections, question)
    if not hits:
        return ("I don't have enough information in the uploaded document(s) to answer that.", [])

    context = "\n\n---\n\n".join(doc.page_content for doc, _score in hits)
    sources = [doc.page_content[:150].replace("\n", " ") + "..." for doc, _score in hits]

    llm = _get_llm()
    prompt = STRICT_QA_PROMPT.format(context=context, question=question)
    response = llm.invoke(prompt)
    return response.content, sources


def summarize_document(collection: str) -> str:
    """Pulls a broad sample of chunks from the collection and summarizes them."""
    store = Chroma(collection_name=collection, embedding_function=_embeddings, persist_directory=CHROMA_DIR)
    all_docs = store.get()["documents"]
    if not all_docs:
        return "No content found to summarize."

    context = "\n\n".join(all_docs[:20])  # cap to keep prompt size reasonable
    llm = _get_llm()
    prompt = SUMMARY_PROMPT.format(context=context)
    response = llm.invoke(prompt)
    return response.content
