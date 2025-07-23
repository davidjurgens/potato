from google import genai

DEFAULT_MODEL = "gemini-2.5-flash"

DEFAULT_HINT_PROMPT = '''
    You are assisting a user with an annotation task. 
        The annotation instruction is : {description} 
        The annotation task type is: {annotation_type}
        The sentence (or item) to annotate is : {text}
        Your goal is to generate a short, helpful hint that guides the annotator in how to think about the input — **without providing the answer**.

        The hint should:
        - Highlight key aspects of the input relevant to the task
        - Encourage thoughtful reasoning or observation
        - Point to subtle features (tone, wording, structure, implication) that matter for the annotation
        - Be specific and informative, not vague or generic
        '''

DEFAULT_KEYWORD_PROMPT = '''
    You are assisting a user with an annotation task. 
        The annotation instruction is : {description} 
        The annotation task type is: {annotation_type}
        The sentence (or item) to annotate is : {text}
        Your goal is : Print out just a sequence of keywords, not sentences, in the text that most relate to the task. Do not explain your answer. Do not print out the entire text. If no part of the text relates to the task, print the empty string.
    '''

class GeminiEndpoint:

    def __init__(self, config: dict):
        # TODO: Deal with custom Gemini options like port and model
        # TODO: Allow for the user to specify the specific hint and highlight prompts

        self.description = config["annotation_schemes"][0]["description"]
        self.annotation_type = config["annotation_schemes"][0]["annotation_type"]
        self.ai_config = config["ai_support"].get("ai_config", {})
        self.api_key = self.ai_config.get("api_key", "")
        self.client = genai.Client(api_key=self.api_key) #Insert api key for test
        
        # Use default values if user sets empty strings
        hint_prompt_config = self.ai_config.get("hint_prompt", DEFAULT_HINT_PROMPT)
        self.hint_prompt = DEFAULT_HINT_PROMPT if hint_prompt_config == "" else hint_prompt_config
        
        keyword_prompt_config = self.ai_config.get("keyword_prompt", DEFAULT_KEYWORD_PROMPT)
        self.keyword_prompt = DEFAULT_KEYWORD_PROMPT if keyword_prompt_config == "" else keyword_prompt_config
        
        model_config = self.ai_config.get("model", DEFAULT_MODEL)
        self.model = DEFAULT_MODEL if model_config == "" else model_config

    def get_hint(self, text: str) -> str:
        '''Interact with the local Gemini API to get a hint for how to annotate the instance'''

        # Generate the default hint prompt or use the custom prompt
        prompt = self.hint_prompt.format(text=text, description=self.description, annotation_type=self.annotation_type)
        print(prompt)
        return self.query(prompt)

    def get_highlights(self, text: str) -> str:
        '''Interact with the local Gemini API to get a hint for how to annotate the instance'''

        # Generate the default keyword prompt or use the custom prompt
        prompt = self.keyword_prompt.format(text=text, description=self.description, annotation_type=self.annotation_type)
        return self.query(prompt)

    def query(self, prompt: str) -> str:
        '''Interact with the Gemini API to get the response to the prompt'''

        
        response = self.client.models.generate_content(
            model=self.model, contents=prompt
        )

        return response.text
    