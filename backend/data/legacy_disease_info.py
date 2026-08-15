"""Disease descriptions curated in Healora's original (pre-database) app.py.

Kept verbatim and moved here unchanged so backend/scripts/seed_diseases.py
can migrate them into the Disease table without losing anything. Not
imported by the running app anymore — descriptions live in the database
after seeding.
"""

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
    "Impetigo": "A highly contagious skin infection that mainly affects infants and children.",
}
