from fastapi import FastAPI
from pydantic import BaseModel
from pipeline import answer_question

app = FastAPI()

class QueryRequest(BaseModel):
    query: str

@app.post("/ask")
def ask_question(request: QueryRequest):
    result = answer_question(request.query)
    return result