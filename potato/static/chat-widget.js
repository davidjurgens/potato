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
    colMd12Element.classList.add('ml-n3');

    // Create chat window as col-md-4
    const chatColumn = document.createElement('div');
    chatColumn.classList.add('col-md-4');
    chatColumn.classList.add('ml-n3');

    chatColumn.innerHTML = `
    <div id="chat-widget" class="shadow d-flex flex-column" style="height: 100%; max-width: 400px; max-height: 80vh;">
      <div class="card-header d-flex justify-content-between align-items-center">
          <span>Chat with Large Language Models</span>
      </div>
      <div id="chat-messages" class="card-body overflow-auto flex-grow-1" style="height: 100%;">
      </div>
      <form class="form-inline p-3">
          <div class="d-flex w-100">
              <input id="chat-input" type="text" class="form-control flex-grow-1 mr-2" placeholder="Type your message...">
              <button id="chat-submit" type="submit" class="btn btn-primary">Send</button>
          </div>
      </form>
  
    </div>
    `;

    // Insert the chat window next to the col-md-8 element
    colMd12Element.parentNode.appendChild(chatColumn);

    this.container = chatColumn;
  }


  attachEventListeners() {
    this.container.querySelector('#chat-submit').addEventListener('click', (event) => {
        event.preventDefault();
        const message = this.container.querySelector('#chat-input').value.trim();
        if (!message) return;
        this.onUserRequest(message);
    });
}

  onUserRequest(message) {
      const messageElement = document.createElement('div');
      messageElement.className = 'text-right mb-2';
      messageElement.innerHTML = `<span class="badge badge-dark">${message}</span>`;
      this.container.querySelector('#chat-messages').appendChild(messageElement);

      setTimeout(() => {
          this.reply('Hello! This is a sample reply.');
      }, 1000);
  }

  reply(message) {
      const replyElement = document.createElement('div');
      replyElement.className = 'text-left mb-2';
      replyElement.innerHTML = `<span class="badge badge-light">${message}</span>`;
      this.container.querySelector('#chat-messages').appendChild(replyElement);
  }
}

document.addEventListener("DOMContentLoaded", function() {
  new ChatWidget();
});
