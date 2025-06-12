import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from google import genai
from google.genai import types
from google.api_core import retry

import os
from os.path import join as file_path
import yaml

DOCS_DIR = 'resources/RAG'

class RagSingleton:
    instance = None
    __initialized = False
    __genai_client = None
    DB_NAME = "rca_info_db"
    db = None
    __embed_fn = None

    def __new__(cls, genai_client):
        if cls.instance is None:
            cls.instance = super(RagSingleton, cls).__new__(cls)
        return cls.instance

    def __init__(self, genai_client):
        if not self.__initialized:
            if genai_client is not None:
                self.__genai_client = genai_client
            else:
                print("Error: Requires genai_client")
                return

            # Load the documents
            documents = []
            for filename in os.listdir(DOCS_DIR):
                with open(file_path(DOCS_DIR, filename), 'r') as file:
                    documents.append(file.read())

            self.__embed_fn = RagSingleton.GeminiEmbeddingFunction()
            # Generate the embeddings
            self.__embed_fn.document_mode = True
            chroma_client = chromadb.Client()
            self.db = chroma_client.get_or_create_collection(name=RagSingleton.DB_NAME, embedding_function=self.__embed_fn)
            self.db.add(documents=documents, ids=[str(i) for i in range(len(documents))])
            print(f"db.count() {self.db.count()}")

            self.__initialized = True

    def query_db(self, query: str) -> str or None:
        print(query)
        if query == "" or query is None:
            return None

        # Switch to query mode when generating embeddings.
        self.__embed_fn.document_mode = False

        # Search the Chroma DB using the specified query.
        #query = "Cisco IOS-XR alarms"

        result = self.db.query(query_texts=[query], n_results=1, include=["documents", "distances"])
        [all_passages] = result["documents"]
        [distances] = result["distances"]

        similarity_threshold = 0.75  # Adjust this threshold as needed.

        distance = distances[0]
        print(f"distance: {distance}")
        passages = None
        if distance < similarity_threshold:  # Lower distance means more relevant.
            print("Relevant results found.")
            passages = ""
            for passage in all_passages:
                passages += f"REFERENCE: {passage.replace("\n", " ")}\n"
        else:
            print("No relevant results found.")

        return passages

    class GeminiEmbeddingFunction(EmbeddingFunction):
        __is_retriable = lambda e: (isinstance(e, genai.errors.APIError) and e.code in {429, 503})

        document_mode = True  # True = Generate embeddings; False = Retrieve

        def __init__(self):
            super().__init__()
            with open('config/conf.yaml', 'r') as stream:
                conf = yaml.load(stream, Loader=yaml.FullLoader)
                GOOGLE_API_KEY = conf['google_gemini_api_key']
            self.__genai_client = genai.Client(api_key=GOOGLE_API_KEY)

        @retry.Retry(predicate=__is_retriable)
        def __call__(self, input: Documents) -> Embeddings:
            if self.document_mode:
                embedding_task = "retrieval_document"
            else:
                embedding_task = "retrieval_query"
            response = self.__genai_client.models.embed_content(
                model="models/text-embedding-004",
                contents=input,
                config=types.EmbedContentConfig(
                    task_type=embedding_task,
                ),
            )
            return [e.values for e in response.embeddings]

if __name__ == "__main__":
    with open('config/conf.yaml', 'r') as stream:
        conf = yaml.load(stream, Loader=yaml.FullLoader)
        GOOGLE_API_KEY = conf['google_gemini_api_key']
        genai_client = genai.Client(api_key=GOOGLE_API_KEY)

    rag = RagSingleton(genai_client)
    print(rag.query_db("Cisco IOS-XR"))