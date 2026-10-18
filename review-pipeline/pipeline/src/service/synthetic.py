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

from ..model import Review, SOURCE_LANGUAGES


PRODUCTS = ["shirt", "hat", "pants", "jacket", "coat", "shoes", "dress", "scarf"]

# Each language provides phrasing for three fragments (fit, material, overall)
# across three sentiment buckets. Fragments compose into a 3-sentence review.
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
    pool = PHRASES[lang]
    parts = [
        rng.choice(pool["fit"][sentiment]),
        rng.choice(pool["material"][sentiment]),
        rng.choice(pool["overall"][sentiment]),
    ]
    return " ".join(parts)


def generate_reviews(count: int, seed: int = 42) -> list[Review]:
    """Return `count` synthetic Review objects, reproducible for a given seed."""
    rng = random.Random(seed)
    today = date.today()
    reviews: list[Review] = []

    for i in range(count):
        lang = rng.choice(SOURCE_LANGUAGES)
        sentiment, (lo, hi) = rng.choice(SENTIMENTS)
        rating = rng.randint(lo, hi)
        product = rng.choice(PRODUCTS)
        text = _compose_review(lang, sentiment, rng)
        review_date = today - timedelta(days=rng.randint(0, 30))

        reviews.append(
            Review(
                review_id=f"rev-{i + 1:04d}",
                product=product,
                source_language=lang,
                rating=rating,
                text=text,
                date=review_date.isoformat(),
            )
        )

    return reviews
