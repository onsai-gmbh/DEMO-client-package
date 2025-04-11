##################
#  CREATE SEPARATE EMBEDDINGS FOR EACH QA
###############

import os
import uuid
import pandas as pd
import pinecone     
import time
from dotenv import load_dotenv
import openpyxl
from bot_embeddings import get_embeddings_sync
import re
import sys
import yaml
load_dotenv()
pinecone_api_key = os.getenv('PINECONE_API_KEY')
pinecone_environment = os.getenv('PINECONE_ENVIRONMENT')
#pinecone_index = os.getenv('PINECONE_INDEX')
pinecone_index = "koncept-test"
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

pinecone.init(      
    api_key=pinecone_api_key,      
    environment=pinecone_environment
)      
index = pinecone.Index(pinecone_index)

def chunks(lst, n):
    """Teilt eine Liste in kleinere Batches der Größe n."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def process_data(file_path, batch_size=100):
    print("Using Index: " + str(pinecone_index))
    print("Waiting 10s")
    time.sleep(10)
    print("Deleting index")
    pinecone.delete_index(pinecone_index)
    print("Waiting 10s")
    time.sleep(10)
    print("Creating index")
    pinecone.create_index(pinecone_index, dimension=1536, pod_type="s1")
    print("Waiting 10s")
    time.sleep(10)

    if file_path.endswith(".xls") or file_path.endswith(".xlsx"):
        df = pd.read_excel(file_path, engine='openpyxl')
        
        # Normalize column names to lowercase for case-insensitive access
        df.columns = [col.lower() for col in df.columns]

        # Rename columns to simplify access
        frage_col = next((c for c in df.columns if "frage" in c), None)
        spezifisch_col = next((c for c in df.columns if "spezifisch" in c), None)
        zur_bearbeitung_col = next((c for c in df.columns if "zur bearbeitung" in c), None)

        if zur_bearbeitung_col:
            df = df[~df[zur_bearbeitung_col].astype(str).str.lower().str.contains('x', na=False)]

        locations = config["hotel_info"]["properties"].keys()

        final_list = []
        failed_embeddings = []

        for idx, row in df.iterrows():
            question_raw = row.get(frage_col)
            if pd.isna(question_raw):
                continue

            # Split questions by comma or period
            phrases = re.split(r'[,]', question_raw)
            phrases = [phrase.strip() for phrase in phrases if phrase.strip()]

            # Get language and 'spezifisch' fields
            uniqe_string = str(row.get(spezifisch_col, "")).strip().lower()
            language = str(row.get("language", "de-DE")).strip()
            if not language or language.lower() == 'nan':
                language = "de-DE"

            uniqe = uniqe_string == "ja"

            for phrase in phrases:
                print(phrase)
                for location_name in locations:
                    answer = row.get(location_name.lower())
                    if pd.isna(answer) or not answer:
                        continue

                    phrase_vector = phrase.strip().strip('.').strip(',').strip('?').lower()
                    answer_vector = answer.strip().strip('.').strip(',').strip('?').lower()
                    print("Phrase after cleaning: " + phrase_vector)

                    meta = {
                        "location": location_name,
                        "uniqe": uniqe,
                        "text": f"{phrase}: {answer}",
                        "language": language
                    }
                    vector_qa = f'Q: {phrase_vector} A: {answer_vector}'
                    vector = get_embeddings_sync(vector_qa)

                    print(f"Phrase: {phrase}, Location: {location_name}, Answer: {answer}, Embedding: {vector}")

                    if not vector:
                        failed_embeddings.append(vector_qa)
                        print(f"Konnte kein Vektor für Phrase generieren: {phrase}", file=sys.stderr)
                        continue

                    tmp = (str(uuid.uuid4()), vector, meta)
                    final_list.append(tmp)

        # Upload in batches
        print(f"Gesamtzahl der Embeddings zum Hochladen: {len(final_list)}")
        print(f"Anzahl der fehlgeschlagenen Embeddings: {len(failed_embeddings)}")
        for batch in chunks(final_list, batch_size):
            try:
                index.upsert(vectors=batch)
                print(f"Hochgeladenes Batch von {len(batch)} Vektoren.")
            except pinecone.core.client.exceptions.ApiException as e:
                print(f"Fehler beim Hochladen eines Batches: {e}", file=sys.stderr)
                continue

if __name__ == "__main__":
    process_data("./data/KONCE_FAQ_08.04.2025.xlsx")
