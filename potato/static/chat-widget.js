class ChatWidget {
  constructor() {
    this.initStyles();
    this.createChatWidget();
    this.attachEventListeners();
  }

  initStyles() {
    // Custom styles for chat widget
    const style = document.createElement('style');
    style.innerHTML = `
    .chat-message-user {
      display: inline-block;
      padding: 10px 15px;
      border-radius: 18px;
      background-color: #a6d8ff;  // Darker shade
      color: white;
      max-width: 80%;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }
    
    .chat-message-assistant {
      display: inline-block;
      padding: 10px 15px;
      border-radius: 18px;
      background-color: #ecf0f1;  // Lighter shade
      color: #2c3e50;  // Dark text for light background
      max-width: 80%;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }

    pre {
      white-space: pre-wrap;       /* Since CSS 2.1 */
      white-space: -moz-pre-wrap;  /* Mozilla, since 1999 */
      white-space: -pre-wrap;      /* Opera 4-6 */
      white-space: -o-pre-wrap;    /* Opera 7 */
      word-wrap: break-word;       /* Internet Explorer 5.5+ */
    }

    #chat-input {
      height: auto;
      max-height: 20vh;
      overflow-y: auto;
      resize: none !important;
  }
  
    `;
    document.head.appendChild(style);
  }

  createChatWidget() {
    const annotationElement = document.querySelector('.annotation_schema');
    if (!annotationElement) return; // Ensure the element exists

    // Traverse up to locate the closest parent with class col-md-12
    const annotationBox = annotationElement.closest('.col-md-12');
    if (!annotationBox) return;  // Ensure the element exists

    // Modify the class of the found col-md-12 element to col-md-8
    annotationBox.classList.remove('col-md-12');
    annotationBox.classList.add('col-md-8');
    annotationBox.classList.add('justify-content-end');

    // Get the computed height of the annotation box
    const annotationComputedHeight = window.getComputedStyle(annotationBox).height;
    // widgetHeight is the minimum of 80vh and the computed height of the annotation box
    const widgetHeight = Math.min(window.innerHeight, parseInt(annotationComputedHeight));

    // Create chat window as col-md-4
    const chatColumn = document.createElement('div');
    chatColumn.classList.add('col-md-4');
    chatColumn.classList.add('justify-content-start');

    chatColumn.innerHTML = `
    <div id="chat-widget" class="card d-flex flex-column" style="height: 100%; max-height: ${widgetHeight};">
      <div class="card-header d-flex justify-content-between align-items-center">
          <span>Chat with Large Language Models</span>
      </div>
      <div id="chat-messages" class="card-body overflow-auto flex-grow-1" style="height: 100%;">
      </div>
      <form class="form-inline p-3">
          <div class="d-flex w-100 flex-wrap">
              <textarea id="chat-input" class="form-control flex-grow-1 mb-1 mr-1" rows="1" placeholder="Ask anything..." style="resize: vertical; overflow-y: auto;"></textarea>
              <button id="chat-submit" type="submit" class="btn btn-secondary mb-1">Send</button>
          </div>
      </form>
  
    </div>
    `;
    // Insert the chat window next to the col-md-8 element
    annotationBox.parentNode.appendChild(chatColumn);
    this.container = chatColumn;
    this.annotationBox = annotationBox;
  }


  attachEventListeners() {
    // Add event listener to the textarea
    const chatInput = document.getElementById('chat-input');
    chatInput.addEventListener('keydown', function (event) {
      // Check if Enter key is pressed
      if (event.key === 'Enter') {
        // If Shift key is also held down, just add a newline and return
        if (event.shiftKey) {
          return;
        }

        // Otherwise, prevent default newline and submit the form
        event.preventDefault();
        // Assuming you have a function to handle the form submission
        // submitFormFunction();
        document.getElementById('chat-submit').click();
      }
    });

    this.submitButton = this.container.querySelector('#chat-submit');
    this.chatForm = this.container.querySelector('form'); // Store the form in a class property for easy access
    this.chatForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const message = this.container.querySelector('#chat-input').value.trim();
      // Clear the input
      this.container.querySelector('#chat-input').value = '';

      if (!message) return;
      this.onUserRequest(message);
    });

    // Initial chat setup
    const instanceContent = this.extractInstanceContent();
    const annotationSchemaContent = this.extractAnnotationSchemaContent();

    if (instanceContent && annotationSchemaContent) {
      // Concatenate the two strings
      const message = instanceContent + '\n\n------\n\n' + annotationSchemaContent;
      this.onUserRequest(message);
    }
  }

  // ==== Chat Widget Methods ====
  addUserMessage(message) {
    const messageElement = document.createElement('div');
    messageElement.className = 'text-right mb-2';
    messageElement.innerHTML = `
    <pre class="chat-message-user text-left">${message}</pre>
    `;

    const chatMessagesContainer = this.container.querySelector('#chat-messages');
    chatMessagesContainer.appendChild(messageElement);

    // Scroll to the bottom
    chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
  }

  addAssistantMessage(message) {
    const messageElement = document.createElement('div');
    messageElement.className = 'text-left mb-2';
    messageElement.innerHTML = `
    <pre class="chat-message-assistant">${message}</pre>
    `;

    const chatMessagesContainer = this.container.querySelector('#chat-messages');
    chatMessagesContainer.appendChild(messageElement);

    // Scroll to the bottom
    chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
  }


  onUserRequest(message) {
    this.addUserMessage(message);
    // Disable the Send button
    this.submitButton.disabled = true;

    // TODO: replace this with API call
    setTimeout(() => {
      this.reply('Hello! This is a sample reply.');
    }, 1000);
  }

  reply(message) {
    this.addAssistantMessage(message);
    // Re-enable the Send button
    this.submitButton.disabled = false;
  }

  // ==== Extracting Content from Annotation Box ====
  // Extract content from .instance
  extractInstanceContent() {
    const instanceElement = this.annotationBox.querySelector('.instance[name="context_text"]');
    return instanceElement ? instanceElement.innerText.trim() : null;
  }

  // Extract content from .annotation_schema
  extractAnnotationSchemaContent() {
    const schemaElement = this.annotationBox.querySelector('.annotation_schema legend');
    return schemaElement ? schemaElement.innerText.trim() : null;
  }
}

document.addEventListener("DOMContentLoaded", function () {
  // only initialize the chat widget if the enable_llm_chat is set to True
  const enableLLMChat = document.getElementById('enable_llm_chat').value;
  if (enableLLMChat === 'True') {
    new ChatWidget();
  }
});
