# Model Card: Threadline Library Recommender + Grounded Archive 0.2

## 1. System Summary

Threadline is a narrative music-discovery prototype. It recommends a track from a listener's exported Apple Music library and uses that artist as an entrance into connected universes, reviewed story chapters, album context, and grounded archive questions.

The homepage accepts any artist search. MusicBrainz supplies an external catalog
identity and release groups, while the smaller reviewed archive supplies the
deeper stories. The interface labels these layers so broad search does not imply
that every result has been editorially reviewed.

The system has three inspectable decision components. A deterministic personal-library recommender ranks existing tracks using available listening metadata. A hybrid playlist-continuation system generates candidates from public listening similarity and reranks them for playlist fit. A retrieval-and-answering system ranks reviewed evidence passages and produces an extractive answer with confidence, claim labels, and citations. None is a trained psychological model or claims to know private thoughts.

## 2. Intended Use

Threadline is intended for listeners who want to rediscover something in their own library and then understand the relationships, events, public statements, and creative eras surrounding it. It supports both newcomers and existing fans. The current version is a classroom prototype and research aid, not a definitive historical authority or production music recommendation service.

## 3. Out-of-Scope Uses

The system should not be used to:

- Diagnose an artist or infer a private psychological state.
- Present criticism, rumors, or fan theories as confirmed biography.
- Prove that one event caused an album or song without explicit evidence.
- Persist or redistribute provider lyrics, copyrighted articles, or private/leaked material in the reviewed archive.
- Treat a concert listing as guaranteed without checking the official event page.
- Treat a recommendation score as a probability or objective measure of taste.
- Upload someone else's private library export without their permission.

## 4. Data and Review Process

The static archive stores short original summaries backed by links to interviews and music reporting. Each evidence passage has a claim type and one or more sources. The current draft contains 22 reviewed story profiles spanning Tyler, the Creator, Odd Future, and the collective's documented members and core music subgroups, including Syd, Frank Ocean, Earl Sweatshirt, Domo Genesis, The Internet, MellowHype, MellowHigh, and others. Separate factual snapshots supply complete Tyler and Odd Future group track indexes plus synchronized album/EP/mixtape catalogs for 20 documented members and core music subgroups. Catalog metadata provides external music and lyrics destinations; it does not become reviewed biography. A separate live MusicBrainz lookup makes other artist identities searchable without generating unreviewed biographies.

The archive's small size is intentional for this first draft. It demonstrates editorial review and cross-universe navigation without pretending to cover every artist. The live event provider is isolated from the historical archive and attaches a retrieval time and verification warning.

Song pages query LRCLIB on demand using title, artist, and album. The client
requires a confident title/artist match, prefers synchronized records, labels
instrumentals, and abstains on ambiguous or missing results. Returned lyric text
is held only in the running app's temporary cache and is not added to the static
catalog or reviewed evidence archive. Each match retains its provider link.
LRCLIB supplies the text and available line timestamps; Threadline owns the
runtime synchronization behavior that follows the YouTube clock, advances and
scrolls the active line, and animates the progressive karaoke fill.

The personal layer accepts an Apple Music XML library or playlist export. It
retains only title, artist, album, genre, play count, skip count, rating, date
added, and last-played date in the current app session. It discards file paths,
comments, account information, and audio. The library data is not added to the
reviewed archive or written to project files.

For playlist continuation, Threadline sends up to six representative seed
artist/title pairs and shortlisted candidate names to Last.fm. The provider
returns similar tracks based on listening data and community tags; the complete
library export is not transmitted. Last.fm similarity is treated as an opaque
behavioral signal, not a literal percentage of shared fans.

## 5. How the AI Works

The personal recommender first builds genre and artist affinities from play counts and ratings. Rediscover emphasizes time away; Comfort emphasizes familiarity; Deep Cut emphasizes lower play counts. All three also use genre affinity, positive play-versus-skip history, and ratings. The result exposes its normalized signals and a plain-language explanation before linking to the artist universe.

Playlist continuation uses two stages. It generates a broad pool from similar
tracks for diverse playlist seeds, then ranks candidates using 40% listening
similarity, 25% mood/category tag fit, 15% multi-seed support, 10% personal
library affinity, and 10% discovery value. Existing playlist tracks are removed,
and the final list is reranked to reduce repeated artists.

The archive retriever tokenizes a question, removes common stop words, and ranks archive passages using term frequency, inverse document frequency, field weighting, phrase matching, and query coverage. The answer engine returns the top reviewed passages only when confidence passes a threshold.

By default, the retriever allows documented facts, artist statements, and reporting. Critical interpretations and fan theories require explicit opt-in. Low-confidence questions produce an abstention rather than a guessed answer.

## 6. Reliability Evaluation

The automated suite covers Apple XML parsing, playlist membership, data minimization, library profiling, recommendation-mode behavior, Last.fm response normalization, seed diversity, hybrid playlist scoring, duplicate filtering, multi-seed aggregation, archive validation, retrieval relevance, abstention, causal-language warnings, and concert-provider failures.

Current local results:

- Unit and integration tests: see the current `pytest` run in the project handoff.
- Personal-library and playlist-continuation tests: **11/11 passed**.
- Structured question-answering cases: **5/5 passed**.
- Unsupported private-detail case: correctly abstained.
- Direct-causation case: answered with an evidence boundary and warning.

These results measure the included cases, not general factual accuracy across all music history.

## 7. Limitations and Biases

The reviewed corpus is very small and currently overrepresents one connected Los Angeles music cluster. A lexical ranker can miss synonyms, indirect references, misspellings, and nuanced questions. Source selection introduces editorial bias: publications with accessible archives are easier to include, while deleted social posts, print-only interviews, and less-covered artists can disappear from the story.

Apple Music exports may omit or lag play counts, skips, ratings, and recent
activity. Genre labels are inconsistent, and unrated tracks receive a neutral
rating signal. The personal rediscovery scorer cannot infer mood, energy,
listening context, or why a track was skipped, and it only ranks tracks already
present in the export. The separate playlist-continuation system can surface
external candidates through Last.fm.

Last.fm similarity and tags have incomplete coverage and reflect that service's
listener population and community vocabulary. A tag such as “sad” is not an
objective acoustic measurement. The current ranker has hand-selected weights;
they need offline holdout evaluation and real add/skip feedback before production
use. Apple Music account writes and storefront-availability checks are not
available from the XML-only workflow.

Claim labels reduce confusion but do not make a source automatically correct. Publications can repeat errors, artists can remember events differently, and the absence of evidence is not proof that an event did not happen. MusicBrainz release-group classifications and artist relationships are community-maintained and can contain omissions, duplicates, misspellings, unofficial collections, or unusual edition choices. The snapshot therefore applies explicit release-type and known-leak exclusions and preserves source links for inspection.

Album-era context is intentionally reused across songs from the same release.
That reuse is not evidence that every track has the same meaning or that every
credited performer shared one mental state. The song page exposes album and song
background as separate layers; when no reviewed public source names the exact
song, the song layer abstains instead of creating a more specific explanation.

LRCLIB coverage is community-maintained and may contain missing lyrics,
incorrect timing, alternate-version mismatches, or transcription errors. Strict
matching reduces but cannot eliminate that risk. The app does not imply that the
LRCLIB server's open-source software license grants rights to lyric text.

## 8. Misuse and Prevention

The largest misuse risk is converting a persuasive narrative into false certainty about relationships, sexuality, conflict, trauma, or mental health. Threadline limits psychological language to artists' own public accounts, presents disagreements separately, labels criticism, displays citations, and abstains when evidence is weak.

The archive should exclude private, leaked, doxxed, or contextless deleted material. Live concert results are visually separated, timestamped, and accompanied by a reminder to verify before purchasing or traveling.

Library exports are personal data. The app explains what it keeps, does not
cache the upload or write it into the archive, and warns that a hosted Streamlit
copy processes the file on that host. Listeners who want the metadata to remain
on their computer should run Threadline locally.

The playlist screen discloses the smaller subset sent to Last.fm before the
user requests matches. Threadline does not claim access to raw fan overlap and
does not send the full uploaded library to the similarity provider.

Lyrics are fetched from LRCLIB only when a listener opens a song, attributed to
the matching provider record, and not copied into Threadline's repository or
reviewed archive. Genius remains an external fallback. Deployers remain
responsible for confirming that their use of provider content is appropriate in
their jurisdiction and product context.

## 9. What Reliability Testing Revealed

Testing showed that a confident-sounding story can collapse multiple evidence levels. The proposed Pharrell-to-Flower Boy example contains a plausible influence, a claimed event, and a critical interpretation, but the reviewed draft did not find a primary source proving the complete causal chain. The system therefore preserves the influence context while explicitly refusing to state direct causation as established fact.

Testing also showed that retrieval confidence is not factual confidence. It measures how closely a question matches reviewed passages; users must still inspect the attached sources.

Recommendation testing showed why one fixed score is a poor description of
intent. A frequently played track is sensible for Comfort but defeats Deep Cut;
explicit modes let the same evidence support different, understandable choices.

Playlist-continuation research showed that the stronger framing is candidate
generation plus reranking. Listening similarity finds plausible neighbors, but
playlist-title/category context and support from multiple seeds are needed to
separate a coherent recommendation from a merely adjacent track.

## 10. Collaboration With AI

A helpful AI suggestion was to separate reviewed historical stories from time-sensitive concert data. That distinction became a real architecture boundary, with a static validated archive and a separate freshness-aware provider.

An initially flawed AI suggestion was to take an early idea about interviews and concerts and immediately narrow the project into a planned "artist discovery journey." That moved to workflow design before the underlying product idea was settled. Human feedback corrected the direction: the concept became a broader connected music-story platform, with Odd Future as an example rather than the product's entire scope.

Human feedback also identified that the classroom recommender felt forced when
it was disconnected from the story product. That changed the design: personal
Apple Music metadata now supplies a meaningful first song, and the artist behind
that recommendation becomes the entrance into Threadline.

## 11. Future Work

Future versions could add an optional MusicKit connection with explicit Apple authorization, direct add-to-playlist actions, Apple personal recommendations as another candidate source, learned ranking from accept/skip feedback, offline playlist holdout evaluation, a documented editorial workflow, broader artist coverage, stronger semantic retrieval, side-by-side conflicting accounts, accessible media embeds, and human evaluation. A generative model could be added only if it remains constrained to cited archive evidence and preserves the current abstention behavior.
