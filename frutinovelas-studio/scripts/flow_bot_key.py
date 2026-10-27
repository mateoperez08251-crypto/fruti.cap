"""Print the local executor key for iniciar_flow_bot.cmd (stdout only; never written to disk)."""
from frutinovelas.services.flow_transport import local_secret

print(local_secret("browser"))
