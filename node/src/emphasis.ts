/*
 * filename: emphasis.ts
 * date: 10/16/2024
 * author: Tristan Hilbert (aka TFlexSoom)
 * desc: Highlights emphasis worthy corpus prompts and annotations
 *   as signaled by the backend.
 * 
 */

function getJsonElement<T>(elementId: string): T | undefined {
    const elem = document.getElementById(elementId);
    if(elem === null) {
        return undefined;
    }

    try{
        return JSON.parse(elem.textContent as string) as T;
    } catch(err) {
        console.warn(`could not parse json element '${elementId}'. Error: ${err}`);
    }

    return undefined;
}

function emphasize(emphasisList: Array<string>) {
    const instanceTextElem = document.getElementById("instance-text");
    if(instanceTextElem === null) {
        console.warn("cannot find instance text");
        return;
    }

    const instanceText = instanceTextElem.textContent;
    if(!instanceText || instanceText === "") {
        console.log("text content in instance");
        return;
    }

    const emphasisSet = new Set(emphasisList);
    const wordList = instanceText.split(" ");
    let result = "";
    for(const word in wordList) {
        if(emphasisSet.has(word)) {
            result += `
            <mark aria-hidden="true" class="emphasis">
                ${word}
            </mark>
            `
        } else {
            // since this is html we don't have to worry about extra spaces
            result += word + " ";
        }
    }

    instanceTextElem.innerHTML = result;
}

function suggest(suggestions: Array<string>) {
    console.log(suggestions);
}

// Main
(function(){
    const emphasis = getJsonElement<Array<string>>("emphasis");
    if(emphasis !== undefined) {
        emphasize(emphasis);
    }

    const suggestions = getJsonElement<Array<string>>("suggestions");
    if(suggestions !== undefined) {
        suggest(suggestions);
    }
    
}())