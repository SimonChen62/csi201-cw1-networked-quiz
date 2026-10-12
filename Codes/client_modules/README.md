# Client module ownership

These files are reserved for D and E. A's temporary test client is under `tests/` and is not the assessed client.

- `connection.py`: D, client socket and JSON-lines receive/send logic.
- `state.py`: D, local user, room and question state.
- `cli.py`: E, terminal input, menus and output.

The final assessed `client.py` will call these modules after D and E agree on their interfaces.
