/*
 * filename: emphasis.ts
 * date: 10/16/2024
 * author: Tristan Hilbert (aka TFlexSoom)
 * desc: Highlights emphasis worthy corpus prompts and annotations
 *   as signaled by the backend.
 * 
 */

import TrieSearch from "trie-search";

// Main
(function(){
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
        
        const emphasisTrie = new TrieSearch<any>(undefined, {
            splitOnRegEx: false,
        });

        emphasisList.map((item) => emphasisTrie.map(item, item));
        const wordList = instanceText.split(" ");
        let lastWasValid = false;
        let last = "";
        let result = "";
        for(const word of wordList) {
            const current = last + word;
            const search = emphasisTrie.search(current);

            if(search.length === 0 && lastWasValid) {
                result += `
                <mark aria-hidden="true" class="emphasis">${last}</mark>
                `;
                
                result += word + ' ';
                last = "";
                lastWasValid = false;
                continue;
            }

            if(search.length === 0) {
                // since this is html we don't have to worry about extra spaces
                result += word + " ";
                last = "";
                continue;
            }

            if(search.length === 1 && search[0] === current) {
                result += `
                <mark aria-hidden="true" class="emphasis">${current}</mark>
                `;
                last = "";
                lastWasValid = false;
                continue;
            }

            if(search.includes(current)) {
                lastWasValid = true;
            }
            
            last = current + " ";
        }

        instanceTextElem.innerHTML = result;
    }

    function suggest(suggestions: Array<string>) {
        console.log(suggestions);
    }


    const emphasis = getJsonElement<Array<string>>("emphasis");
    if(emphasis !== undefined) {
        emphasize(emphasis);
    }

    const suggestions = getJsonElement<Array<string>>("suggestions");
    if(suggestions !== undefined) {
        suggest(suggestions);
    }
}());