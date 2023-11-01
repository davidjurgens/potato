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
    
    .chat-message-reply {
      display: inline-block;
      padding: 10px 15px;
      border-radius: 18px;
      background-color: #ecf0f1;  // Lighter shade
      color: #2c3e50;  // Dark text for light background
      max-width: 80%;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }
    `;
    document.head.appendChild(style);
  }

  createChatWidget() {
    const annotationElement = document.querySelector('.annotation_schema');
    if (!annotationElement) return; // Ensure the element exists

    // Traverse up to locate the closest parent with class col-md-12
    const colMd12Element = annotationElement.closest('.col-md-12');
    if (!colMd12Element) return;  // Ensure the element exists

    // Modify the class of the found col-md-12 element to col-md-8
    colMd12Element.classList.remove('col-md-12');
    colMd12Element.classList.add('col-md-8');
    colMd12Element.classList.add('justify-content-end');

    // Create chat window as col-md-4
    const chatColumn = document.createElement('div');
    chatColumn.classList.add('col-md-4');
    chatColumn.classList.add('justify-content-start');

    chatColumn.innerHTML = `
    <div id="chat-widget" class="card d-flex flex-column" style="height: 100%; max-width: 400px; max-height: 80vh;">
      <div class="card-header d-flex justify-content-between align-items-center">
          <span>Chat with Large Language Models</span>
      </div>
      <div id="chat-messages" class="card-body overflow-auto flex-grow-1" style="height: 100%;">
      </div>
      <form class="form-inline p-3">
          <div class="d-flex w-100">
              <input id="chat-input" type="text" class="form-control flex-grow-1 mr-2" placeholder="Type your message...">
              <button id="chat-submit" type="submit" class="btn btn-secondary">Send</button>
          </div>
      </form>
  
    </div>
    `;

    // Insert the chat window next to the col-md-8 element
    colMd12Element.parentNode.appendChild(chatColumn);

    this.container = chatColumn;
  }


  attachEventListeners() {

    this.submitButton = this.container.querySelector('#chat-submit'); // Store the button in a class property for easy access
    this.submitButton.addEventListener('click', (event) => {
        event.preventDefault();
        const message = this.container.querySelector('#chat-input').value.trim();
        // Clear the input
        this.container.querySelector('#chat-input').value = '';

        if (!message) return;
        this.onUserRequest(message);
    });
}

  onUserRequest(message) {
      const messageElement = document.createElement('div');
      messageElement.className = 'text-right mb-2';
      messageElement.innerHTML = `<span class="chat-message-user">${message}</span>`;
      this.container.querySelector('#chat-messages').appendChild(messageElement);

      // Disable the Send button
      this.submitButton.disabled = true;

      // TODO: replace this with API call
      setTimeout(() => {
          this.reply('Hello! This is a sample reply.');
      }, 1000);
  }

  reply(message) {
      const replyElement = document.createElement('div');
      replyElement.className = 'text-left mb-2';
      replyElement.innerHTML = `<span class="chat-message-reply">${message}</span>`;
      this.container.querySelector('#chat-messages').appendChild(replyElement);

      // Re-enable the Send button
      this.submitButton.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", function() {
  new ChatWidget();
});
