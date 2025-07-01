from google import genai

DEFAULT_MODEL = "gemini-2.5-flash"
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

class GeminiEndpoint:

    def __init__(self, config: dict):
        # TODO: Deal with custom Ollama options like port and model
        # TODO: Allow for the user to specify the specific hint and highlight prompts

        gemini_config = config.get("gemini_config", {})
        self.hint_prompt = gemini_config.get("hint_prompt", DEFAULT_HINT_PROMPT)
        self.highlight_prompt = gemini_config.get("highlight_prompt", DEFAULT_HIGHLIGHT_PROMPT)
        self.model = gemini_config.get("model", DEFAULT_MODEL)
        self.instructions = gemini_config.get("instructions") #custom instruction for tasks

    def get_hint(self, text: str) -> str:
        '''Interact with the local Gemini API to get a hint for how to annotate the instance'''

        # Generate the hint prompt
        prompt = self.hint_prompt.format(instructions=self.instructions, text=text)
        return self.query(prompt)

    def get_highlights(self, text: str) -> str:
        '''Interact with the local Gemini API to get a hint for how to annotate the instance'''

        # Generate the prompt to get a highlight passage
        prompt = self.highlight_prompt.format(instructions=self.instructions, text=text)
        return self.query(prompt)

    def query(self, prompt: str) -> str:
        '''Interact with the local Gemini API to get the response to the prompt'''

        client = genai.Client(api_key="") #Insert api key for test

        response = client.models.generate_content(
            model=self.model, contents=prompt
        )

        return response.text
    