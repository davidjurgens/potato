#!/usr/bin/env python3
"""
Generate a test dataset for Potato's solo mode emotion classification testing.

Produces:
  - tests/data/solo_mode_emotion_data.json  (JSON array for Potato)
  - tests/data/solo_mode_emotion_gold.json  (dict for the simulator)

Usage:
    python tests/data/generate_solo_test_data.py
"""

import json
import os
import random
from collections import Counter
from pathlib import Path

random.seed(42)

TASK_INSTRUCTIONS = """## Emotion Classification Task

You will be shown short texts (social media posts, product reviews, personal statements).
Your job is to classify the **primary emotion** expressed by the author.

### Labels

- **joy**: The author expresses happiness, excitement, gratitude, or satisfaction.
- **sadness**: The author expresses grief, disappointment, loneliness, or melancholy.
- **anger**: The author expresses frustration, outrage, irritation, or hostility.
- **fear**: The author expresses anxiety, worry, dread, or panic.
- **surprise**: The author expresses astonishment, shock, disbelief, or an unexpected reaction.
- **neutral**: The text conveys no clear emotion; it is factual or informational.

### Guidelines

1. Focus on the **author's** emotion, not the emotion described in the text.
2. If the text contains multiple emotions, choose the **dominant** one.
3. Sarcasm should be interpreted by its *intended* meaning, not its literal words.
4. Short exclamations (e.g., "Wow!") should be classified by surrounding context.
5. If you genuinely cannot determine an emotion, choose **neutral**.
"""

# ---------------------------------------------------------------------------
# Templates per emotion
# ---------------------------------------------------------------------------

JOY_TEMPLATES = [
    "Just got promoted at work! {extra}",
    "My {pet} learned a new trick today and I can't stop smiling.",
    "Finally finished {project} after months of effort. Feels amazing!",
    "Best {meal} I've ever had at {place}. Highly recommend!",
    "Woke up to {good_news}. What a wonderful day!",
    "Spent the whole afternoon {activity} with {person} and loved every minute.",
    "Can't believe {team} actually won! {celebration}",
    "This {product} is incredible. {praise}",
    "Today marks {milestone}. So grateful for everyone who helped.",
    "The sunset tonight was absolutely breathtaking. {extra}",
]

JOY_FILLS = {
    "extra": [
        "I've been working toward this for years.",
        "Feeling so blessed right now.",
        "Everything is coming together.",
        "Life is good.",
        "Couldn't be happier!",
    ],
    "pet": ["dog", "cat", "parrot", "rabbit"],
    "project": [
        "my novel", "the kitchen renovation", "my thesis",
        "that side project", "the garden redesign",
    ],
    "meal": ["pizza", "sushi", "brunch", "pasta", "taco"],
    "place": [
        "that new downtown spot", "the farmers market cafe",
        "my neighbor's cookout", "the rooftop restaurant",
    ],
    "good_news": [
        "a surprise package from a friend",
        "an acceptance letter",
        "the best email of my life",
        "flowers on my doorstep",
    ],
    "activity": ["hiking", "painting", "baking", "kayaking", "gardening"],
    "person": ["my best friend", "my family", "the kids", "my partner"],
    "team": ["the Packers", "our local squad", "the underdog team"],
    "celebration": ["We're going to the finals!", "What a comeback!", "Party time!"],
    "product": ["camera", "laptop", "espresso machine", "e-reader", "headset"],
    "praise": [
        "Worth every penny.", "Game changer.", "Five stars easily.",
        "Exceeded all expectations.",
    ],
    "milestone": [
        "five years at this company", "our 10th anniversary",
        "one year since I started this journey", "100 days streak",
    ],
}

SADNESS_TEMPLATES = [
    "I still can't believe {person} is gone. {extra}",
    "Didn't get the {opportunity}. Back to square one.",
    "Feeling really lonely tonight. {extra}",
    "My {item} broke today and it was the last thing {person_ref} gave me.",
    "Another rejection email. {extra}",
    "Watched our old {media} together and just started crying.",
    "It's been {time} and I still think about {memory} every day.",
    "The house feels so empty since {event}.",
    "I tried so hard but it still wasn't enough. {extra}",
    "Rain all week. Matches my mood perfectly.",
]

SADNESS_FILLS = {
    "person": ["grandma", "my mentor", "our dog Max", "uncle Joe"],
    "extra": [
        "Miss them every day.", "I don't know how to move on.",
        "Some days are harder than others.", "The grief just hits out of nowhere.",
        "Wish I could turn back time.",
    ],
    "opportunity": [
        "scholarship", "job offer", "grant", "promotion",
        "apartment I wanted",
    ],
    "item": ["watch", "necklace", "guitar", "mug"],
    "person_ref": ["my grandmother", "dad", "my best friend"],
    "media": ["home videos", "photo albums", "favorite songs"],
    "time": ["three months", "a year", "six weeks"],
    "memory": ["that summer", "our last conversation", "the trip we planned"],
    "event": [
        "the kids moved out", "she left", "the move",
        "the funeral",
    ],
}

ANGER_TEMPLATES = [
    "Waited {time} on hold just to be told {outcome}. Unbelievable.",
    "My {relation} keeps {behavior} and I've had it.",
    "This {product} broke after {duration}. {extra}",
    "How is it legal to charge {amount} for {service}?!",
    "Someone {action} and didn't even apologize. {extra}",
    "The {entity} lied to us again. {extra}",
    "I specifically asked for {request} and got the exact opposite.",
    "Third time this month my {thing} has {problem}. Done with this brand.",
    "Stop telling me to calm down when you caused the problem!",
    "Can't believe they {injustice}. {extra}",
]

ANGER_FILLS = {
    "time": ["45 minutes", "two hours", "an entire afternoon"],
    "outcome": [
        "they can't help me", "the office is closed",
        "I need to call back tomorrow", "my file was lost",
    ],
    "relation": ["neighbor", "coworker", "roommate", "landlord"],
    "behavior": [
        "blasting music at midnight", "parking in my spot",
        "leaving messes everywhere", "ignoring my messages",
    ],
    "product": ["blender", "phone", "dishwasher", "laptop"],
    "duration": ["two weeks", "three days", "one month"],
    "extra": [
        "Never buying from them again.", "Absolutely furious.",
        "This is completely unacceptable.", "I want a refund NOW.",
        "People need to know about this.",
    ],
    "amount": ["$200", "$50", "$80 a month"],
    "service": ["parking", "a simple oil change", "basic internet"],
    "action": ["cut in front of me in line", "scratched my car", "stole my idea at work"],
    "entity": ["the company", "city council", "management", "the airline"],
    "request": ["no onions", "a window seat", "express shipping"],
    "thing": ["order", "delivery", "subscription"],
    "problem": ["arrived damaged", "been delayed", "been wrong"],
    "injustice": [
        "canceled the event with no notice",
        "raised prices again while cutting quality",
        "fired her for speaking up",
    ],
}

FEAR_TEMPLATES = [
    "Just heard {noise} outside and I'm home alone. {extra}",
    "The doctor wants to run more tests. {extra}",
    "I have to {task} tomorrow and I'm terrified.",
    "My {account} was compromised. {extra}",
    "The storm warnings keep getting worse. {extra}",
    "Can't sleep. Keep thinking about {worry}.",
    "What if {scenario}? I can't stop spiraling.",
    "The {area} near my house is flooded and the water is still rising.",
    "Every time I check the news I feel more anxious. {extra}",
    "I don't feel safe walking here after dark anymore.",
]

FEAR_FILLS = {
    "noise": [
        "a loud crash", "footsteps on the porch",
        "glass breaking", "someone trying the door handle",
    ],
    "extra": [
        "My hands are shaking.", "I don't know what to do.",
        "Trying to stay calm but failing.", "Please let everything be okay.",
        "I feel paralyzed.",
    ],
    "task": [
        "present to the entire board", "fly for the first time",
        "go through the MRI", "testify in court",
    ],
    "account": ["bank account", "email", "social media"],
    "worry": [
        "the layoffs", "whether the biopsy is positive",
        "the earthquake forecast", "losing my housing",
    ],
    "scenario": [
        "the company goes under", "I don't pass the exam",
        "the treatment doesn't work", "they find out",
    ],
    "area": ["street", "neighborhood", "road", "park"],
}

SURPRISE_TEMPLATES = [
    "Wait, {person} is {revelation}?! Since when?!",
    "I just found {discovery} in my {location}. What on earth?",
    "Plot twist: {twist}. Did NOT see that coming.",
    "Opened my door to find {unexpected}. I have so many questions.",
    "They just announced {announcement}. Is this real?",
    "I've lived here {time} and never knew {fact}.",
    "Out of nowhere, {event}. I'm still processing.",
    "My {test} results came back and {result}. I'm speechless.",
    "Ran into {person} at {place} of all places. Small world!",
    "The ending of {media} completely blindsided me.",
]

SURPRISE_FILLS = {
    "person": ["my boss", "Sarah", "the quiet kid from school", "my cousin"],
    "revelation": [
        "moving to Japan", "a published author", "engaged",
        "running for office",
    ],
    "discovery": [
        "a $100 bill", "a hidden room", "love letters from the 1940s",
        "a family of raccoons",
    ],
    "location": ["attic", "old jacket", "backyard", "storage unit"],
    "twist": [
        "the intern is the CEO's kid",
        "they were twins the whole time",
        "the restaurant is closing permanently tomorrow",
    ],
    "unexpected": [
        "a puppy with a bow on it", "a film crew",
        "my ex with flowers", "a delivery I never ordered",
    ],
    "announcement": [
        "free tuition for everyone", "the merger",
        "a surprise holiday on Monday", "they're shutting down the project",
    ],
    "time": ["10 years", "my whole life", "three years"],
    "fact": [
        "there's a speakeasy behind the bookstore",
        "the park has underground tunnels",
        "my neighbor is a famous musician",
    ],
    "event": [
        "my phone rang and it was a job offer",
        "the power went out citywide",
        "a deer walked through the office parking lot",
    ],
    "test": ["DNA", "blood", "aptitude", "allergy"],
    "result": [
        "I'm apparently 30% Scandinavian",
        "everything is completely normal",
        "I scored in the 99th percentile",
    ],
    "place": [
        "the airport in Tokyo", "a tiny village in Portugal",
        "the grocery store at 2 AM",
    ],
    "media": ["that show", "the book", "the documentary", "the movie"],
}

NEUTRAL_TEMPLATES = [
    "The meeting is scheduled for {time} in {room}.",
    "Updated the {document} with the latest {data}.",
    "The {item} weighs approximately {weight} and measures {size}.",
    "Reminder: {event} is on {date}.",
    "According to the report, {stat}.",
    "Turned in the {assignment} before the deadline.",
    "The {place} closes at {time_close} on weekdays.",
    "Switched from {old} to {new} for the {purpose}.",
    "Here's the summary: {summary}.",
    "The package arrived. It contains {contents}.",
]

NEUTRAL_FILLS = {
    "time": ["3 PM", "10 AM", "noon"],
    "room": ["conference room B", "the main hall", "room 204"],
    "document": ["spreadsheet", "wiki page", "project plan"],
    "data": ["Q3 numbers", "team assignments", "vendor contacts"],
    "item": ["shipment", "sample", "prototype"],
    "weight": ["2.5 kg", "500 grams", "12 pounds"],
    "size": ["30 x 20 cm", "about a foot long", "standard letter size"],
    "event": [
        "the quarterly review", "the dentist appointment",
        "the software update", "the maintenance window",
    ],
    "date": ["Friday", "March 12", "next Tuesday"],
    "stat": [
        "usage increased 12% quarter over quarter",
        "the average response time is 4.3 seconds",
        "48% of respondents preferred option A",
    ],
    "assignment": ["homework", "proposal draft", "expense report"],
    "place": ["library", "office", "lab", "clinic"],
    "time_close": ["6 PM", "5 PM", "9 PM"],
    "old": ["Slack", "Python 3.9", "the old vendor"],
    "new": ["Teams", "Python 3.12", "a local supplier"],
    "purpose": ["internal comms", "the build pipeline", "catering"],
    "summary": [
        "three action items, two pending reviews",
        "all systems operational, no incidents this week",
        "revenue flat, costs down 3%",
    ],
    "contents": [
        "the replacement parts we ordered",
        "six textbooks and a lab manual",
        "three samples for testing",
    ],
}

# Ambiguous / boundary-case texts (hand-written for realism)
AMBIGUOUS_INSTANCES = [
    {
        "text": "Oh great, another Monday. Can't wait to sit in traffic for two hours.",
        "gold_label": "anger",
        "note": "sarcasm: literal joy words, intended anger/frustration",
    },
    {
        "text": "Well that was certainly... an experience. I'll never forget it.",
        "gold_label": "surprise",
        "note": "vague valence, could be positive or negative surprise",
    },
    {
        "text": "Laughing so hard I'm crying. This is the worst day of my life.",
        "gold_label": "sadness",
        "note": "mixed signals: laughter + worst day",
    },
    {
        "text": "I can't believe they actually did it. I genuinely can't believe it.",
        "gold_label": "surprise",
        "note": "surprise that could be positive or negative",
    },
    {
        "text": "Thanks for nothing, customer service. You've really outdone yourselves.",
        "gold_label": "anger",
        "note": "sarcastic gratitude masking frustration",
    },
    {
        "text": "She's finally at peace. I should be happy for her but I just feel empty.",
        "gold_label": "sadness",
        "note": "bittersweet: relief + grief",
    },
    {
        "text": "Wow, they gave me exactly what I asked for. First time for everything I guess.",
        "gold_label": "surprise",
        "note": "surprise mixed with sarcastic low expectations",
    },
    {
        "text": "I passed! Barely, but I passed. Not sure if I should celebrate or panic about next semester.",
        "gold_label": "joy",
        "note": "joy mixed with anxiety about the future",
    },
    {
        "text": "My ex texted me happy birthday. Don't know how to feel about that.",
        "gold_label": "neutral",
        "note": "genuinely ambiguous emotional state",
    },
    {
        "text": "It's fine. Everything's fine. I'm fine.",
        "gold_label": "sadness",
        "note": "denial pattern suggesting suppressed sadness",
    },
    {
        "text": "Just watched my childhood home get demolished. Progress, they call it.",
        "gold_label": "sadness",
        "note": "loss framed as neutral fact",
    },
    {
        "text": "So apparently I've been pronouncing my coworker's name wrong for three years.",
        "gold_label": "surprise",
        "note": "mild surprise mixed with embarrassment",
    },
    {
        "text": "The kids are finally asleep. Silence has never been this loud.",
        "gold_label": "neutral",
        "note": "could be relief (joy), exhaustion (neutral), or loneliness (sadness)",
    },
    {
        "text": "I got the results. Not what I expected. Need some time to process.",
        "gold_label": "fear",
        "note": "ambiguous: could be surprise, fear, or sadness",
    },
    {
        "text": "Funny how the people who say 'I'm always here for you' are never actually here.",
        "gold_label": "anger",
        "note": "anger and sadness intertwined",
    },
    {
        "text": "Can't stop replaying the conversation in my head. Should I have said something different?",
        "gold_label": "fear",
        "note": "anxiety/rumination, could also be sadness/regret",
    },
    {
        "text": "They threw me a surprise party. I hate surprises. But I love these people.",
        "gold_label": "joy",
        "note": "conflicting emotions resolved toward joy",
    },
    {
        "text": "Moving to a new city next month. Excited and terrified in equal measure.",
        "gold_label": "fear",
        "note": "genuine 50/50 split between joy and fear",
    },
    {
        "text": "My review said I'm 'meeting expectations.' Not exceeding. Just meeting.",
        "gold_label": "sadness",
        "note": "disappointment that could also be anger",
    },
    {
        "text": "LOL this is absolutely ridiculous. Who approved this design?",
        "gold_label": "anger",
        "note": "laughter masking frustration",
    },
    {
        "text": "The algorithm recommended my own blog post back to me. Peak internet.",
        "gold_label": "surprise",
        "note": "amusement and surprise, mildly neutral",
    },
    {
        "text": "I keep refreshing my email even though I know the decision won't come until Friday.",
        "gold_label": "fear",
        "note": "anxiety presented as mundane behavior",
    },
    {
        "text": "Cleaned out the garage and found my dad's old tools. Spent an hour just holding them.",
        "gold_label": "sadness",
        "note": "nostalgia that blurs joy and sadness",
    },
    {
        "text": "Sure, let's have another meeting about the meetings we keep having. Very productive.",
        "gold_label": "anger",
        "note": "workplace sarcasm, frustration",
    },
    {
        "text": "The sunset was beautiful but all I could think about was how she would have loved it.",
        "gold_label": "sadness",
        "note": "beauty triggering grief",
    },
    {
        "text": "I won the argument but somehow I feel like I lost.",
        "gold_label": "sadness",
        "note": "pyrrhic victory, mixed anger and sadness",
    },
    {
        "text": "Interesting. Very interesting. I'll have to think about this.",
        "gold_label": "neutral",
        "note": "deliberately flat affect, could mask any emotion",
    },
    {
        "text": "My plant is thriving. At least something in my life is growing.",
        "gold_label": "sadness",
        "note": "self-deprecating humor mixing small joy with broader sadness",
    },
    {
        "text": "Overheard someone complimenting my work without knowing I was there. Weird feeling.",
        "gold_label": "joy",
        "note": "quiet joy mixed with awkwardness",
    },
    {
        "text": "They postponed the deadline. Again. Not sure if that's a relief or a warning sign.",
        "gold_label": "neutral",
        "note": "genuine uncertainty between relief and worry",
    },
]


def fill_template(template: str, fills: dict) -> str:
    """Replace {placeholders} in template with random choices from fills."""
    result = template
    # Find all placeholders
    import re
    placeholders = re.findall(r"\{(\w+)\}", template)
    for ph in placeholders:
        if ph in fills:
            result = result.replace("{" + ph + "}", random.choice(fills[ph]), 1)
    return result


def generate_instances_from_templates(
    label: str, templates: list, fills: dict, count: int, id_offset: int
) -> list:
    """Generate `count` instances for a given emotion label."""
    instances = []
    for i in range(count):
        tmpl = templates[i % len(templates)]
        text = fill_template(tmpl, fills)
        instance_id = f"emo_{id_offset + i + 1:03d}"
        instances.append({
            "id": instance_id,
            "text": text,
            "gold_label": label,
        })
    return instances


def main():
    script_dir = Path(__file__).resolve().parent
    data_path = script_dir / "solo_mode_emotion_data.json"
    gold_path = script_dir / "solo_mode_emotion_gold.json"

    all_instances = []
    id_offset = 0

    # Emotion -> (templates, fills, target_count)
    emotions = [
        ("joy",      JOY_TEMPLATES,      JOY_FILLS,      45),
        ("sadness",  SADNESS_TEMPLATES,   SADNESS_FILLS,  40),
        ("anger",    ANGER_TEMPLATES,     ANGER_FILLS,    35),
        ("fear",     FEAR_TEMPLATES,      FEAR_FILLS,     30),
        ("surprise", SURPRISE_TEMPLATES,  SURPRISE_FILLS, 30),
        ("neutral",  NEUTRAL_TEMPLATES,   NEUTRAL_FILLS,  40),
    ]

    for label, templates, fills, count in emotions:
        batch = generate_instances_from_templates(
            label, templates, fills, count, id_offset
        )
        all_instances.extend(batch)
        id_offset += count

    # Add ambiguous boundary cases
    for i, case in enumerate(AMBIGUOUS_INSTANCES):
        instance_id = f"emo_{id_offset + i + 1:03d}"
        all_instances.append({
            "id": instance_id,
            "text": case["text"],
            "gold_label": case["gold_label"],
        })

    # Shuffle for a natural ordering
    random.shuffle(all_instances)

    # Write data file (JSON array for Potato)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(all_instances, f, indent=2, ensure_ascii=False)

    # Write gold file (dict for the simulator)
    gold = {
        inst["id"]: {"emotion": inst["gold_label"]}
        for inst in all_instances
    }
    with open(gold_path, "w", encoding="utf-8") as f:
        json.dump(gold, f, indent=2, ensure_ascii=False)

    # Print statistics
    label_counts = Counter(inst["gold_label"] for inst in all_instances)
    print(f"Generated {len(all_instances)} instances total")
    print(f"  Data file:  {data_path}")
    print(f"  Gold file:  {gold_path}")
    print()
    print("Label distribution:")
    for label in ["joy", "sadness", "anger", "fear", "surprise", "neutral"]:
        count = label_counts.get(label, 0)
        pct = 100 * count / len(all_instances)
        print(f"  {label:>10s}: {count:3d}  ({pct:5.1f}%)")
    print(f"  {'TOTAL':>10s}: {len(all_instances):3d}")

    # Count how many are from the ambiguous set
    ambiguous_labels = Counter(c["gold_label"] for c in AMBIGUOUS_INSTANCES)
    print(f"\nAmbiguous boundary cases: {len(AMBIGUOUS_INSTANCES)}")
    for label, cnt in sorted(ambiguous_labels.items()):
        print(f"  {label:>10s}: {cnt}")


if __name__ == "__main__":
    main()
