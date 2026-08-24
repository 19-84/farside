# Browser extension setup

Farside doesn't have its own browser extension, but it works with
[Redirector](https://github.com/einaregilsson/Redirector), available for Firefox, Chrome,
Edge and Opera.

Replace `<your-host>` below with the Farside instance you're using. The original public
instance, `farside.link`, has been shut down — see the [README](../README.md) for running
your own.

## Setup

Install Redirector, then add the following entries.

### General entry

| field | value |
|---|---|
| Description | `[Farside] General Entry` |
| Example URL | `https://m.youtube.com/watch?v=dQw4w9WgXcQ` |
| Pattern type | Regular Expression |

Include pattern:

```
^(?:https?://)?(?:www\.)?(?:\w{2,}\.)?(?:mobile\.|m\.)?((?:imdb|imgur|instagram|medium|odysee|quora|reddit|tiktok|translate\.google|wikipedia|youtube)\.(?:com|org|au|de|co|cn).*)$
```

Redirect to:

```
https://<your-host>/$1
```

### Optional language-wiki entry

The pattern above doesn't cover language-specific Wikipedia links, which need a second entry.

> [!IMPORTANT]
> Position this entry **above** the general entry in Redirector so it takes precedence.

| field | value |
|---|---|
| Description | `[Farside] Optional Language Wiki Entry` |
| Example URL | `https://www.de.m.wikipedia.org/wiki/Atom-U-Boot#Antriebstechnik` |
| Pattern type | Regular Expression |

Include pattern:

```
^(?:https?://)?(?:www\.)?(?:(\w{2,})\.)?(?:mobile\.|m\.)?(wikipedia\.org.*?)(?:(/wiki/.*?)(#.*))?$
```

Redirect to:

```
https://<your-host>/$2$3?lang=$1$4
```

---

These patterns originally came from the upstream project's wiki, contributed by
[@LangLangBart](https://github.com/LangLangBart) in benbusby/farside#64. That wiki lives on
an archived repository, so the instructions are kept here — adapted for self-hosting — to
keep them available.
