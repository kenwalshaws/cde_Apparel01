# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Synthetic review generation.

Service-layer helper that builds a no-PII apparel-review corpus spanning
several source languages and a sentiment range. Lives in `src/` so both the
Lambda handler and the local CLI script can call it (the CLI is a thin wrapper
around `generate_reviews`).

No reviewer names or emails are produced — real PII is a separate,
customer-owned workstream.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from ..debug import debug_print
from ..model import Review


PRODUCTS = ["shirt", "hat", "pants", "jacket", "coat", "shoes", "dress", "scarf"]

# Word pools used to compose a marketing-style product name, e.g.
# "Classic Cotton Shirt" or "Heritage Wool Coat".
_NAME_ADJECTIVES = [
    "Classic", "Heritage", "Everyday", "Signature", "Essential",
    "Vintage", "Modern", "Tailored", "Premium", "Urban",
]
_NAME_MATERIALS = [
    "Cotton", "Wool", "Linen", "Denim", "Merino", "Oxford", "Canvas", "Suede",
]


def _product_name(product: str, rng: random.Random) -> str:
    """Compose a marketing-style product name from the category."""
    adjective = rng.choice(_NAME_ADJECTIVES)
    # Include a material roughly two-thirds of the time for variety.
    if rng.random() < 0.67:
        material = rng.choice(_NAME_MATERIALS)
        return f"{adjective} {material} {product.capitalize()}"
    return f"{adjective} {product.capitalize()}"

# Each language provides phrasing for several aspects across three sentiment
# buckets. English (the only source language used now) has enough aspects to
# compose 5-8 sentence reviews; see _compose_review.
PHRASES: dict[str, dict[str, dict[str, list[str]]]] = {
    "en": {
        "fit": {
            "pos": ["The fit is spot on.", "It fits perfectly."],
            "mid": ["The fit is a little loose.", "The sizing runs slightly large."],
            "neg": ["The fit is way off.", "It runs far too small."],
        },
        "material": {
            "pos": ["The fabric feels soft and well made.", "The material is excellent quality."],
            "mid": ["The material is okay, nothing special.", "The fabric is a bit thin."],
            "neg": ["The fabric feels cheap.", "The material frayed after one wash."],
        },
        "color": {
            "pos": ["The color is rich and exactly as pictured.", "The shade looks great in person."],
            "mid": ["The color is close to the photos but slightly duller.", "The shade is fine, a touch off."],
            "neg": ["The color is nothing like the listing photos.", "The shade faded after the first wash."],
        },
        "comfort": {
            "pos": ["It is really comfortable to wear all day.", "It feels soft against the skin."],
            "mid": ["It is reasonably comfortable once broken in.", "Comfort is average, nothing to note."],
            "neg": ["It is itchy and uncomfortable.", "It feels stiff and never softened up."],
        },
        "delivery": {
            "pos": ["Delivery was fast and the packaging was neat.", "It arrived a day early and well packed."],
            "mid": ["Delivery took about as long as expected.", "Shipping was on time, packaging was plain."],
            "neg": ["Delivery was slow and the box was crushed.", "It took two weeks longer than promised."],
        },
        "value": {
            "pos": ["Great value for the price.", "Well worth what I paid."],
            "mid": ["The price feels about right for what you get.", "Fairly priced, not a steal."],
            "neg": ["Overpriced for the quality.", "Not worth the money at all."],
        },
        "overall": {
            "pos": ["Very satisfied with this purchase.", "I would happily buy it again."],
            "mid": ["It is fine for the price.", "An average buy overall."],
            "neg": ["Disappointed with this one.", "I would not recommend it."],
        },
    },
    "fr": {
        "fit": {
            "pos": ["La coupe est parfaite.", "Il taille très bien."],
            "mid": ["La coupe est un peu large.", "La taille est légèrement grande."],
            "neg": ["La coupe est complètement ratée.", "Il taille beaucoup trop petit."],
        },
        "material": {
            "pos": ["Le tissu est doux et de bonne qualité.", "La matière est excellente."],
            "mid": ["La matière est correcte, sans plus.", "Le tissu est un peu fin."],
            "neg": ["Le tissu fait bon marché.", "La matière s'est effilochée au premier lavage."],
        },
        "overall": {
            "pos": ["Très satisfait de cet achat.", "Je le rachèterais sans hésiter."],
            "mid": ["Correct pour le prix.", "Un achat moyen dans l'ensemble."],
            "neg": ["Déçu par cet article.", "Je ne le recommanderais pas."],
        },
    },
    "de": {
        "fit": {
            "pos": ["Die Passform sitzt perfekt.", "Es passt wie angegossen."],
            "mid": ["Die Passform ist etwas weit.", "Die Größe fällt leicht groß aus."],
            "neg": ["Die Passform ist völlig daneben.", "Es fällt viel zu klein aus."],
        },
        "material": {
            "pos": ["Der Stoff fühlt sich weich und hochwertig an.", "Das Material ist ausgezeichnet."],
            "mid": ["Das Material ist okay, nichts Besonderes.", "Der Stoff ist etwas dünn."],
            "neg": ["Der Stoff wirkt billig.", "Das Material franste nach einer Wäsche aus."],
        },
        "overall": {
            "pos": ["Sehr zufrieden mit diesem Kauf.", "Ich würde es jederzeit wieder kaufen."],
            "mid": ["Für den Preis in Ordnung.", "Insgesamt ein durchschnittlicher Kauf."],
            "neg": ["Von diesem Artikel enttäuscht.", "Ich würde es nicht empfehlen."],
        },
    },
    "es": {
        "fit": {
            "pos": ["El ajuste es perfecto.", "Queda estupendamente."],
            "mid": ["El ajuste es un poco holgado.", "La talla es ligeramente grande."],
            "neg": ["El ajuste está muy mal.", "La talla es demasiado pequeña."],
        },
        "material": {
            "pos": ["La tela es suave y de buena calidad.", "El material es excelente."],
            "mid": ["El material está bien, nada especial.", "La tela es un poco fina."],
            "neg": ["La tela parece barata.", "El material se deshilachó tras un lavado."],
        },
        "overall": {
            "pos": ["Muy satisfecho con esta compra.", "Lo compraría de nuevo sin dudarlo."],
            "mid": ["Está bien por el precio.", "Una compra promedio en general."],
            "neg": ["Decepcionado con este artículo.", "No lo recomendaría."],
        },
    },
    "it": {
        "fit": {
            "pos": ["La vestibilità è perfetta.", "Calza benissimo."],
            "mid": ["La vestibilità è un po' larga.", "La taglia è leggermente grande."],
            "neg": ["La vestibilità è completamente sbagliata.", "Veste troppo stretto."],
        },
        "material": {
            "pos": ["Il tessuto è morbido e di buona qualità.", "Il materiale è eccellente."],
            "mid": ["Il materiale è discreto, niente di speciale.", "Il tessuto è un po' sottile."],
            "neg": ["Il tessuto sembra economico.", "Il materiale si è sfilacciato dopo un lavaggio."],
        },
        "overall": {
            "pos": ["Molto soddisfatto di questo acquisto.", "Lo ricomprerei senza esitazione."],
            "mid": ["Va bene per il prezzo.", "Un acquisto nella media."],
            "neg": ["Deluso da questo articolo.", "Non lo consiglierei."],
        },
    },
    "nl": {
        "fit": {
            "pos": ["De pasvorm is perfect.", "Het zit als gegoten."],
            "mid": ["De pasvorm is wat ruim.", "De maat valt iets groot uit."],
            "neg": ["De pasvorm is helemaal verkeerd.", "Het valt veel te klein uit."],
        },
        "material": {
            "pos": ["De stof voelt zacht en goed gemaakt.", "Het materiaal is uitstekend."],
            "mid": ["Het materiaal is oké, niets bijzonders.", "De stof is wat dun."],
            "neg": ["De stof voelt goedkoop.", "Het materiaal rafelde na één wasbeurt."],
        },
        "overall": {
            "pos": ["Zeer tevreden met deze aankoop.", "Ik zou het zo weer kopen."],
            "mid": ["Prima voor de prijs.", "Al met al een gemiddelde aankoop."],
            "neg": ["Teleurgesteld in dit artikel.", "Ik zou het niet aanraden."],
        },
    },
}

# Sentiment bucket -> (rating range, phrase key).
SENTIMENTS = [
    ("neg", (1, 2)),
    ("mid", (3, 3)),
    ("pos", (4, 5)),
]


def _compose_review(lang: str, sentiment: str, rng: random.Random) -> str:
    """Compose a 5-8 sentence review from the aspect pools.

    Leads with the fit aspect and closes with the overall aspect; the middle is
    a random selection of the remaining aspects. Target length is 5-8 sentences
    when the language has enough aspects (English); languages with fewer aspects
    use all of them.
    """
    pool = PHRASES[lang]
    all_aspects = list(pool.keys())

    lead = "fit" if "fit" in pool else all_aspects[0]
    close = "overall" if "overall" in pool else all_aspects[-1]
    middle_aspects = [a for a in all_aspects if a not in (lead, close)]

    target = rng.randint(5, 8)
    # Sentences needed from the middle (lead + close are fixed).
    need_middle = max(0, target - 2)
    rng.shuffle(middle_aspects)
    chosen_middle = middle_aspects[:need_middle]

    ordered = [lead, *chosen_middle, close]
    parts = [rng.choice(pool[aspect][sentiment]) for aspect in ordered]
    return " ".join(parts)


def generate_reviews(count: int, seed: int = 42) -> list[Review]:
    """Return `count` synthetic Review objects, reproducible for a given seed.

    This use case produces English-only reviews: summarization and the
    summary-translation steps operate on English source text.
    """
    rng = random.Random(seed)
    today = date.today()
    reviews: list[Review] = []

    for i in range(count):
        lang = "en"  # English-only source for this use case.
        sentiment, (lo, hi) = rng.choice(SENTIMENTS)
        rating = rng.randint(lo, hi)
        product = rng.choice(PRODUCTS)
        text = _compose_review(lang, sentiment, rng)
        review_date = today - timedelta(days=rng.randint(0, 30))

        # Unique, human-readable product id per review: PRD-<seq>-<rand hex>.
        # Seeded, so a given (count, seed) reproduces the same ids.
        product_id = f"PRD-{i + 1:04d}-{rng.randrange(16**6):06x}"
        product_name = _product_name(product, rng)

        reviews.append(
            Review(
                review_id=f"rev-{i + 1:04d}",
                product=product,
                product_id=product_id,
                product_name=product_name,
                source_language=lang,
                rating=rating,
                text=text,
                date=review_date.isoformat(),
            )
        )

    debug_print(f"generated {len(reviews)} English reviews (seed={seed})")
    return reviews
