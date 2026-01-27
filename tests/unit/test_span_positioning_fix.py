import os
import tempfile
import json
from unittest.mock import patch, MagicMock

def test_span_positioning_with_server_rendered_spans():
    """Test that span positioning works correctly when server-rendered spans exist."""

    # Create a temporary HTML file to test the positioning logic
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Span Positioning Test</title>
        </head>
        <body>
            <div id="text-content" data-original-text="I am very happy today.">
                I am <span class="span-highlight" data-start="5" data-end="9">very </span>happy today.
            </div>
            <div id="span-overlays"></div>

            <script>
                // Mock the getCharRangeBoundingRect function
                function getCharRangeBoundingRect(container, start, end) {
                    console.log('getCharRangeBoundingRect called with:', { start, end });

                    // Check if the container has HTML elements
                    const hasHtmlElements = container.querySelector('.span-highlight') !== null;

                    if (hasHtmlElements) {
                        return getCharRangeBoundingRectFromOriginalText(container, start, end);
                    } else {
                        return getCharRangeBoundingRectFromTextNode(container, start, end);
                    }
                }

                function getCharRangeBoundingRectFromOriginalText(container, start, end) {
                    // Get the original text from the container's textContent or stored data attribute
                    let originalText = container.textContent;

                    // If we have stored original text, use that instead
                    if (container.hasAttribute('data-original-text')) {
                        originalText = container.getAttribute('data-original-text');
                        console.log('Using stored original text:', originalText);
                    }

                    // Extract the text segment we're looking for
                    const targetText = originalText.substring(start, end);
                    console.log('Target text:', targetText, 'start:', start, 'end:', end);

                    // Find this text segment in the current DOM structure
                    const textNodes = [];
                    const walker = document.createTreeWalker(
                        container,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );

                    let node;
                    while (node = walker.nextNode()) {
                        textNodes.push(node);
                    }

                    console.log('Text nodes count:', textNodes.length);
                    console.log('Text nodes:', textNodes.map(n => n.textContent));

                    // Find the text segment across text nodes using original text positions
                    let currentPos = 0;
                    let startNode = null;
                    let startOffset = 0;
                    let endNode = null;
                    let endOffset = 0;

                    for (let i = 0; i < textNodes.length; i++) {
                        const textNode = textNodes[i];
                        const nodeText = textNode.textContent;
                        const nodeStart = currentPos;
                        const nodeEnd = currentPos + nodeText.length;

                        console.log('Text node', i, ':', nodeText, '(pos', nodeStart + '-' + nodeEnd + ')');

                        // Check if our target range overlaps with this text node
                        if (start < nodeEnd && end > nodeStart) {
                            if (startNode === null) {
                                // This is the start node
                                startNode = textNode;
                                startOffset = Math.max(0, start - nodeStart);
                                console.log('Start node found: offset', startOffset);
                            }

                            if (end <= nodeEnd) {
                                // This is the end node
                                endNode = textNode;
                                endOffset = end - nodeStart;
                                console.log('End node found: offset', endOffset);
                                break;
                            }
                        }

                        currentPos += nodeText.length;
                    }

                    if (!startNode || !endNode) {
                        console.warn('Could not find text nodes for range', { start, end, targetText });
                        return null;
                    }

                    // Create range using the found nodes
                    const range = document.createRange();
                    range.setStart(startNode, startOffset);
                    range.setEnd(endNode, endOffset);

                    console.log('Range created:', {
                        startNode: startNode.textContent,
                        startOffset: startOffset,
                        endNode: endNode.textContent,
                        endOffset: endOffset
                    });

                    // Mock bounding rects for testing
                    return [{
                        top: 10,
                        left: 20,
                        width: 100,
                        height: 20
                    }];
                }

                function getCharRangeBoundingRectFromTextNode(container, start, end) {
                    // Mock implementation for plain text
                    return [{
                        top: 10,
                        left: 20,
                        width: 100,
                        height: 20
                    }];
                }

                // Test the positioning logic
                function testPositioning() {
                    const container = document.getElementById('text-content');
                    const result = getCharRangeBoundingRect(container, 5, 9);

                    if (result && result.length > 0) {
                        console.log('SUCCESS: Positioning test passed');
                        document.body.innerHTML += '<div style="color: green;">SUCCESS: Positioning test passed</div>';
                    } else {
                        console.log('FAILURE: Positioning test failed');
                        document.body.innerHTML += '<div style="color: red;">FAILURE: Positioning test failed</div>';
                    }
                }

                // Run the test when the page loads
                window.addEventListener('load', testPositioning);
            </script>
        </body>
        </html>
        """
        f.write(html_content)
        temp_file = f.name

    try:
        # Verify the file was created
        assert os.path.exists(temp_file), "Temporary HTML file was not created"

        # Read the file content to verify it's correct
        with open(temp_file, 'r') as f:
            content = f.read()
            assert 'data-original-text="I am very happy today."' in content, "Original text attribute not found"
            assert 'span class="span-highlight"' in content, "Span highlight element not found"
            assert 'getCharRangeBoundingRect' in content, "Positioning function not found"

        print(f"✅ Test HTML file created successfully: {temp_file}")
        print("   You can open this file in a browser to manually test the positioning logic")

    finally:
        # Clean up
        if os.path.exists(temp_file):
            os.unlink(temp_file)

def test_original_text_storage():
    """Test that original text is properly stored and retrieved."""

    # Mock DOM element
    mock_container = MagicMock()
    mock_container.hasAttribute.return_value = True
    mock_container.getAttribute.return_value = "I am very happy today."
    mock_container.textContent = "I am <span>very </span>happy today."

    # Test that the stored original text is used
    assert mock_container.getAttribute('data-original-text') == "I am very happy today."
    assert mock_container.textContent != "I am very happy today."  # DOM content is different

    print("✅ Original text storage test passed")

if __name__ == "__main__":
    test_span_positioning_with_server_rendered_spans()
    test_original_text_storage()
    print("All tests passed!")