import ollama

class OllamaClient:

    def summarize(self, query, search_results):

        context = "\n\n".join([
            f"Source: {r.title}\nURL: {r.url}\n"
            f"{(r.extracted_content or r.content)[:1500]}"
            for r in search_results
        ])

        prompt = f"""You are a research assistant. Answer using ONLY the sources below. Be concise. Max 300 words.

QUERY: {query}

SOURCES:
{context}"""

        response = ollama.chat(
            model="qwen2.5-coder:7b-instruct-q4_K_M",
            messages=[{"role": "user", "content": prompt}],
            options={
                "num_predict": 512,
                "temperature": 0.3,
            }
        )

        return response["message"]["content"]