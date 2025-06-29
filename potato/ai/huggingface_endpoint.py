from huggingface_hub import InferenceClient



DEFAULT_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
DEFAULT_HINT_PROMPT = '''
Your task is the following: {instructions}
The text is: "{text}"
Generate a hint for how to annotate this instance without saying the actual answer.
'''
DEFAULT_HIGHLIGHT_PROMPT = '''
The given task is the following: {instructions}
The text is: "{text}"
Your task is : Print out just a sequence of keywords, not sentences, in the text that most relate to the task. Do not explain your answer. Do not print out the entire text. If no part of the text relates to the task, print the empty string.
'''

class HuggingfaceEndpoint:

    def __init__(self, config: dict):
        # TODO: Deal with custom Ollama options like port and model
        # TODO: Allow for the user to specify the specific hint and highlight prompts

        huggingface_config = config.get("huggingface_config", {})
        self.hint_prompt = huggingface_config.get("hint_prompt", DEFAULT_HINT_PROMPT)
        self.highlight_prompt = huggingface_config.get("highlight_prompt", DEFAULT_HIGHLIGHT_PROMPT)
        self.model = huggingface_config.get("model", DEFAULT_MODEL)
        self.instructions = huggingface_config.get("instructions") #custom instruction for tasks
        self.client = InferenceClient(
        model=self.model,
        token="", #Insert api key for testing
        )

    def get_hint(self, text: str) -> str:
        '''Interact with the local Huggingfcace API to get a hint for how to annotate the instance'''

        # Generate the hint prompt
        prompt = self.hint_prompt.format(instructions=self.instructions, text=text)
        return self.query(prompt)

    def get_highlights(self, text: str) -> str:
        '''Interact with the local Huggingfcace API to get a hint for how to annotate the instance'''

        # Generate the prompt to get a highlight passage
        prompt = self.highlight_prompt.format(instructions=self.instructions, text=text)
        return self.query(prompt)

    def query(self, prompt: str) -> str:
        '''Interact with the local Huggingfcace API to get the response to the prompt'''

        response = self.client.chat_completion(
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=100
        )
        # Extract the generated text from the conversational response
        generated_text = response.choices[0].message.content
        return generated_text
