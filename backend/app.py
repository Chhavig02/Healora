import pandas as pd
import numpy as np
import random
from flask import Flask, request, jsonify
from flask_cors import CORS
from sklearn import preprocessing
from sklearn.tree import DecisionTreeClassifier, _tree
from sklearn.model_selection import train_test_split
import warnings
import os

warnings.filterwarnings("ignore", category=DeprecationWarning)

app = Flask(__name__)
CORS(app)

# --- AI Logic Ported from original script ---

# Importing the dataset
training = pd.read_csv('backend/Training.csv')
testing = pd.read_csv('backend/Testing.csv')
doc_consult = pd.read_csv('backend/doc_consult.csv')

cols = training.columns
cols = cols[:-1]

x = training[cols]
y = training['prognosis']

# dimensionality Reduction for removing redundancies
reduced_data = training.groupby(training['prognosis']).max()

# encoding/mapping String values to integer constants
le = preprocessing.LabelEncoder()
le.fit(y)
y = le.transform(y)

# implement the Decision-Tree-Classifier
clf1 = DecisionTreeClassifier()
clf = clf1.fit(x, y) # Training on full data for the API

GREETING_INPUTS = ("hello", "hi", "greetings", "sup", "what's up", "hey", "start", "checkup")
GREETING_RESPONSES = [
    "Hello! I'm here to help you understand your symptoms. How are you feeling today?",
    "Hi there! I'm your Healtho AI assistant. Please tell me what's bothering you.",
    "Greetings! Let's perform a quick health assessment. What symptoms are you experiencing?",
    "Hello! I'm ready to help. Feel free to describe your symptoms in your own words."
]

DISEASE_INFO = {
    "Fungal infection": "A common skin condition caused by fungi. It often presents as itchy, red patches.",
    "Allergy": "Your immune system's reaction to a substance that isn't typically harmful.",
    "GERD": "Gastroesophageal reflux disease occurs when stomach acid frequently flows back into the tube connecting your mouth and stomach.",
    "Chronic cholestasis": "A condition where bile cannot flow from the liver to the duodenum.",
    "Drug Reaction": "An adverse effect caused by a medication.",
    "Peptic ulcer disease": "Sores that develop on the lining of the stomach, lower esophagus, or small intestine.",
    "AIDS": "A chronic, potentially life-threatening condition caused by the human immunodeficiency virus (HIV).",
    "Diabetes ": "A group of diseases that result in too much sugar in the blood (high blood glucose).",
    "Gastroenteritis": "Intestinal infection marked by diarrhea, cramps, nausea, vomiting, and fever.",
    "Bronchial Asthma": "A condition in which your airways narrow and swell and may produce extra mucus.",
    "Hypertension ": "A condition in which the force of the blood against your artery walls is too high.",
    "Migraine": "A headache that can cause severe throbbing pain or a pulsing sensation, usually on one side of the head.",
    "Cervical spondylosis": "Age-related wear and tear affecting the spinal disks in your neck.",
    "Paralysis (brain hemorrhage)": "Loss of muscle function in part of your body. It happens when something goes wrong with the way messages pass between your brain and muscles.",
    "Jaundice": "A condition in which the skin, whites of the eyes and mucous membranes turn yellow because of a high level of bilirubin.",
    "Malaria": "A disease caused by a parasite. The parasite is transmitted to humans through the bites of infected mosquitoes.",
    "Chicken pox": "A highly contagious viral infection causing an itchy, blister-like rash on the skin.",
    "Dengue": "A mosquito-borne viral disease occurring in tropical and subtropical areas.",
    "Typhoid": "An infectious bacterial fever with an eruption of red spots on the chest and abdomen and severe intestinal irritation.",
    "hepatitis A": "A highly contagious liver infection caused by the hepatitis A virus.",
    "Hepatitis B": "A serious liver infection caused by the hepatitis B virus.",
    "Hepatitis C": "An infection caused by a virus that attacks the liver and leads to inflammation.",
    "Hepatitis D": "A liver disease caused by the hepatitis D virus, which only occurs in people who are also infected with the hepatitis B virus.",
    "Hepatitis E": "A liver disease caused by the hepatitis E virus.",
    "Alcoholic hepatitis": "Liver inflammation caused by drinking too much alcohol.",
    "Tuberculosis": "A potentially serious infectious disease that mainly affects the lungs.",
    "Common Cold": "A viral infection of your nose and throat.",
    "Pneumonia": "An infection that inflames the air sacs in one or both lungs.",
    "Dimorphic hemmorhoids(piles)": "Swollen veins in your anus and lower rectum, similar to varicose veins.",
    "Heart attack": "A medical emergency where the supply of blood to the heart is suddenly blocked.",
    "Varicose veins": "Gnarled, enlarged veins, most commonly appearing in the legs and feet.",
    "Hypothyroidism": "A condition in which the thyroid gland doesn't produce enough thyroid hormone.",
    "Hyperthyroidism": "The production of too much thyroxine hormone by the thyroid gland.",
    "Hypoglycemia": "A condition in which your blood sugar (glucose) level is lower than normal.",
    "Osteoarthristis": "A type of arthritis that occurs when flexible tissue at the ends of bones wears down.",
    "Arthritis": "The swelling and tenderness of one or more of your joints.",
    "(vertigo) Paroymsal  Positional Vertigo": "A common cause of vertigo — the sudden sensation that you're spinning or that the inside of your head is spinning.",
    "Acne": "A skin condition that occurs when your hair follicles become plugged with oil and dead skin cells.",
    "Urinary tract infection": "An infection in any part of the urinary system, the kidneys, bladder, or urethra.",
    "Psoriasis": "A condition in which skin cells build up and form scales and itchy, dry patches.",
    "Impetigo": "A highly contagious skin infection that mainly affects infants and children."
}

def get_disease_info(node_value):
    val = node_value.nonzero()
    disease = le.inverse_transform(val[0])
    return disease[0]

def get_next_step(answers):
    """
    answers: list of (symptom_name, bool_value)
    """
    symptoms_yes = [a[0] for a in answers if a[1]]
    symptoms_no = [a[0] for a in answers if not a[1]]

    # 1. Symptom Matching Logic (Prioritize what the user says)
    if symptoms_yes:
        scores = {}
        for disease in reduced_data.index:
            # Symptoms for this disease
            disease_symptoms = set(reduced_data.columns[reduced_data.loc[disease].values.nonzero()])
            
            # Intersection with user "Yes" symptoms
            overlap = len(set(symptoms_yes).intersection(disease_symptoms))
            # Penalty for missing "Yes" symptoms (optional)
            
            # Intersection with user "No" symptoms (should be 0)
            penalty = len(set(symptoms_no).intersection(disease_symptoms))
            
            if overlap > 0:
                # Score = Overlap - Penalty + small tie-breaker for fewer symptoms overall
                scores[disease] = (overlap * 10) - (penalty * 5) - (len(disease_symptoms) * 0.1)

        if scores:
            best_disease = max(scores, key=scores.get)
            best_score = scores[best_disease]
            
            # If we have a very strong match (>2 symptoms overlap or perfect match)
            if best_score > 15 or len(symptoms_yes) >= 3:
                disease = best_disease
                risk = 0
                risk_row = doc_consult[doc_consult.iloc[:, 0] == disease]
                if not risk_row.empty:
                    risk = int(risk_row.iloc[0, 1])
                
                symptoms_given = list(reduced_data.columns[reduced_data.loc[disease].values.nonzero()])
                
                return {
                    "type": "result",
                    "disease": disease,
                    "description": DISEASE_INFO.get(disease, "Please consult a medical professional for more details."),
                    "risk": risk,
                    "confidence": min(100, int((best_score / (len(symptoms_yes) * 10)) * 100)) if symptoms_yes else 100,
                    "symptoms": [s.replace('_', ' ') for s in symptoms_given],
                    "symptoms_present": [s.replace('_', ' ') for s in symptoms_yes]
                }

    # 2. Tree-based Guided Questioning (Fall back to tree if not sure)
    tree_ = clf.tree_
    feature_name = [
        cols[i] if i != _tree.TREE_UNDEFINED else "undefined!"
        for i in tree_.feature
    ]

    current_node = 0
    while tree_.feature[current_node] != _tree.TREE_UNDEFINED:
        name = feature_name[current_node]
        user_val = next((1 if a[1] else 0 for a in answers if a[0] == name), None)
        
        if user_val is None:
            return {
                "type": "question",
                "symptom": name.replace('_', ' ').capitalize() + "?",
                "raw_symptom": name
            }
        
        if user_val <= tree_.threshold[current_node]:
            current_node = tree_.children_left[current_node]
        else:
            current_node = tree_.children_right[current_node]
            
    # Reached a leaf
    disease = le.inverse_transform([np.argmax(tree_.value[current_node])])[0]
    risk_row = doc_consult[doc_consult.iloc[:, 0] == disease]
    risk = int(risk_row.iloc[0, 1]) if not risk_row.empty else 0
    symptoms_given = list(reduced_data.columns[reduced_data.loc[disease].values.nonzero()])
    
    return {
        "type": "result",
        "disease": disease,
        "description": DISEASE_INFO.get(disease, "Please consult a medical professional for more details."),
        "risk": risk,
        "confidence": 100,
        "symptoms": [s.replace('_', ' ') for s in symptoms_given],
        "symptoms_present": [s.replace('_', ' ') for s in symptoms_yes]
    }

def extract_symptoms(text):
    text = text.lower().replace(' ', '_')
    words = text.split('_')
    found = []
    
    for symptom in cols:
        symptom_clean = symptom.lower()
        # Check for exact match
        if symptom_clean in text:
            found.append(symptom)
            continue
        
        # Check for partial matches (e.g. "fever" matches "high_fever")
        # Only if the word is specific enough
        parts = symptom_clean.split('_')
        for part in parts:
            if len(part) > 3 and part in words:
                found.append(symptom)
                break
                
    return list(set(found))

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    user_input = data.get('message', '').lower()
    answers = data.get('answers', []) # list of [symptom, value]

    # 1. Extract symptoms from natural language input
    new_symptoms = extract_symptoms(user_input)
    for s in new_symptoms:
        # Check if already answered
        if not any(a[0] == s for a in answers):
            answers.append([s, True])

    # 2. Handle reset/bye
    if 'bye' in user_input or 'exit' in user_input:
        return jsonify({"message": "Bye! Take care.", "next_step": {"type": "reset"}})

    # 3. Handle greetings if no symptoms found yet
    if not answers and any(word in user_input for word in GREETING_INPUTS):
        response = random.choice(GREETING_RESPONSES)
        return jsonify({
            "message": response + ". Please describe your symptoms or just say 'start' to begin a check.",
            "next_step": {"type": "waiting"}
        })

    # 4. Continue diagnostic process
    next_step = get_next_step(answers)
    
    # If we found symptoms in the text, we might have jumped ahead
    # Provide a feedback message
    message = None
    if new_symptoms:
        message = f"I've noted that you have: {', '.join([s.replace('_', ' ') for s in new_symptoms])}."
    
    return jsonify({
        "message": message,
        "next_step": next_step,
        "answers": answers # Return updated answers to the frontend
    })

@app.route('/api/symptoms', methods=['GET'])
def get_all_symptoms():
    return jsonify({"symptoms": [s.replace('_', ' ') for s in cols]})

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Healtho Backend is running", "endpoints": ["/api/chat", "/api/symptoms"]})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
