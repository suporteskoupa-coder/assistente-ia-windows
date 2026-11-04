from ultron.events import Event


class FakeBrain:
    """Cérebro falso: devolve eventos roteirizados e grava o que recebeu."""

    def __init__(self, name="claude", script=None, summary="resumo do chat"):
        self.name = name
        self.calls = []
        self.script = script
        self.summary = summary

    async def send(self, session_id, history, text, system, chat_ref=None):
        self.calls.append({"session_id": session_id, "history": history, "text": text, "system": system, "chat_ref": chat_ref})
        if text.startswith("Resuma"):
            yield Event("text", self.summary)
            yield Event("done")
            return
        for ev in self.script or [Event("session", data={"id": "s1"}), Event("tool", data={"name": "abrir_jogo", "input": {"nome": "cs"}}),
                                  Event("text", "Abrindo"), Event("text", "o CS."), Event("done")]:
            yield ev
