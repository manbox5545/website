MPOXEL CHESS 3D
===============

Setup
-----
1. Put the whole folder on a static web host (Firebase Hosting, GitHub Pages, etc.).
2. Enable Firebase Authentication > Email/Password.
3. Enable Firebase Realtime Database.
4. Publish firebase.rules.json as the Realtime Database rules.
5. Open index.html through a web server/hosting URL. Do not use file:// because ES modules and model loading need HTTP(S).

Features
--------
- Firebase email/password accounts
- DP color
- Create/join 6-character servers
- Real-time room presence
- Real-time chess state synchronized through Firebase
- Full chess move legality via chess.js (check/checkmate, castling, en-passant, promotion, draw detection)
- 3D board/pieces using the supplied ChessBoard.obj + ChessBoard.mtl
- Piece movement animations
- Room chat
- Golden MPOXEL UI

The supplied OBJ contains the board and individual named piece meshes. The app uses those meshes as the visual piece sources and repositions clones from the synchronized chess position.
