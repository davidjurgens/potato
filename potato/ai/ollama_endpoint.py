import ollama

DEFAULT_MODEL = "llama3.2"
DEFAULT_HINT_PROMPT = '''
Your task is the following: {instructions}
The text is: "{text}"
Generate a hint for how to annotate this instance without saying the actual answer.
'''
DEFAULT_HIGHLIGHT_PROMPT = '''
Your task is the following: {instructions}
The text is: "{text}"
Print out a sequence of words in the text that most relate to the task. Do not explain your answer. Do not print out the entire text. If no part of the text relates to the task, print the empty string.
'''

class OllamaEndpoint:

    def __init__(self, config: dict):
        # TODO: Deal with custom Ollama options like port and model
        # TODO: Allow for the user to specify the specific hint and highlight prompts

        ollama_config = config.get("ollama_config", {})

        self.hint_prompt = ollama_config.get("hint_prompt", DEFAULT_HINT_PROMPT)
        self.highlight_prompt = ollama_config.get("highlight_prompt", DEFAULT_HIGHLIGHT_PROMPT)
        self.model = ollama_config.get("model", DEFAULT_MODEL)

    def get_hint(self, instructions: str, text: str) -> str:
        '''Interact with the local Ollama API to get a hint for how to annotate the instance'''

        # Generate the hint prompt
        prompt = self.hint_prompt.format(instructions=instructions, text=text)
        return self.query(prompt)

    def get_highlights(self, instructions: str, text: str) -> str:
        '''Interact with the local Ollama API to get a hint for how to annotate the instance'''

        # Generate the prompt to get a highlight passage
        prompt = self.hint_prompt.format(instructions=instructions, text=text)
        return self.query(prompt)

    def query(self, prompt: str) -> str:
        '''Interact with the local Ollama API to get the response to the prompt'''
        response = ollama.chat(model='llama3.1', messages=[
            {
                'role': 'user',
                'content': prompt,
            },
        ])

        return response['message']['content']