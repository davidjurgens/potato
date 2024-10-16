/*
 * filename: emphasis.ts
 * date: 10/16/2024
 * author: Tristan Hilbert (aka TFlexSoom)
 * desc: Highlights emphasis worthy corpus prompts and annotations
 *   as signaled by the backend.
 * 
 */

function getJsonElement(elementId: string): Record<string, any> | undefined {
    let elem = document.getElementById(elementId);
    if(elem === null) {
        return undefined;
    }

    try{
        JSON.parse(elem.textContent as string);
    } catch(err) {
        console.warn(`could not parse json element '${elementId}'. Error: ${err}`);
    }

    return undefined;
}

// Main
(function(){
    let emphasis = getJsonElement("emphasis");
    


    let suggestions = getJsonElement("suggestions");

    
}())