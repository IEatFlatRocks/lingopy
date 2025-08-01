document.addEventListener('DOMContentLoaded', function() {
    // --- Element References ---
    const player = document.getElementById('video-player');
    const lang1Select = document.getElementById('lang1-select');
    const lang2Select = document.getElementById('lang2-select');
    const lyricsPane = document.getElementById('lyrics-pane');
    const loopToggleBtn = document.getElementById('loop-toggle');
    const popup = document.getElementById('definition-popup');
    const popupWord = document.getElementById('popup-word');
    const popupDefinition = document.getElementById('popup-definition');
    const popupCloseBtn = document.getElementById('popup-close');
    const popupSaveBtn = document.getElementById('popup-save');

    // --- State Variables ---
    let isLooping = false;
    let activeBlockForLoop = null;
    let subtitles1 = [];
    let subtitles2 = [];
    let combinedSubtitles = [];

    // --- Core Functions ---
    async function handleLanguageChange() {
        await loadSubtitles(lang1Select.value, subtitles1);
        await loadSubtitles(lang2Select.value, subtitles2);
        combineAndDisplaySubtitles();
    }

    async function loadSubtitles(url, subtitleArray) {
        subtitleArray.length = 0;
        if (!url) return;
        try {
            const response = await fetch(url);
            const srtText = await response.text();
            subtitleArray.push(...parseSRT(srtText));
        } catch (error) {
            console.error('Error loading subtitles:', error);
        }
    }
    
    function combineAndDisplaySubtitles() {
        lyricsPane.innerHTML = '';
        combinedSubtitles.length = 0;
        subtitles1.forEach((sub1, index) => {
            const sub2 = subtitles2.find(s => sub1.start < s.end && sub1.end > s.start);
            const block = {
                id: `block-${index}`,
                start: sub1.start,
                end: sub1.end,
                text1: sub1.text,
                text2: sub2 ? sub2.text : '',
            };
            combinedSubtitles.push(block);

            const blockDiv = document.createElement('div');
            blockDiv.className = 'lyric-block';
            blockDiv.id = block.id;

            const p1 = document.createElement('p');
            p1.className = 'caption-line lang1';
            p1.dataset.lang = lang1Select.selectedOptions[0].textContent;
            p1.innerHTML = wrapWordsInSpans(block.text1);
            
            // --- UPDATED: Add a check before seeking ---
            p1.onclick = () => {
                // Only seek if the current time is outside this subtitle's range
                if (player.currentTime < block.start || player.currentTime >= block.end) {
                    player.currentTime = block.start;
                }
            };
            blockDiv.appendChild(p1);

            if (block.text2) {
                const p2 = document.createElement('p');
                p2.className = 'caption-line lang2';
                p2.dataset.lang = lang2Select.selectedOptions[0].textContent;
                p2.innerHTML = wrapWordsInSpans(block.text2);
                // --- UPDATED: Add the same check here ---
                p2.onclick = () => {
                    if (player.currentTime < block.start || player.currentTime >= block.end) {
                        player.currentTime = block.start;
                    }
                };
                blockDiv.appendChild(p2);
            }
            lyricsPane.appendChild(blockDiv);
        });
    }

    // --- Synchronization, Scrolling, and Looping ---
    function syncLyrics() {
        const currentTime = player.currentTime;
        const activeBlock = combinedSubtitles.find(b => currentTime >= b.start && currentTime < b.end);

        if (activeBlock) {
            activeBlockForLoop = activeBlock;
        }

        if (isLooping && activeBlockForLoop && currentTime > activeBlockForLoop.end) {
            player.currentTime = activeBlockForLoop.start;
            player.play();
            return;
        }
        
        lyricsPane.querySelectorAll('.caption-line').forEach(p => p.classList.remove('highlight'));
        
        if (activeBlock) {
            const activeBlockDiv = document.getElementById(activeBlock.id);
            if (activeBlockDiv) {
                activeBlockDiv.querySelectorAll('.caption-line').forEach(p => p.classList.add('highlight'));
                const paneRect = lyricsPane.getBoundingClientRect();
                const blockRect = activeBlockDiv.getBoundingClientRect();
                const scrollOffset = (blockRect.top - paneRect.top) - (paneRect.height / 2) + (blockRect.height / 2);
                lyricsPane.scrollTop += scrollOffset;
            }
        }
    }
    
    // --- Helper Functions ---
    function wrapWordsInSpans(text) {
        const words = text.split(/(\s+|<br>)/);
        return words.map(word => {
            if (word.trim() === '' || word.startsWith('<')) return word;
            const cleanWord = word.replace(/[.,!?]/g, '');
            return `<span class="clickable-word" data-word="${cleanWord}">${word}</span>`;
        }).join('');
    }


    function parseSRT(srtText) {
        const subs = [];
        // Normalize line endings and split by ANY newline
        const lines = srtText.trim().replace(/\r/g, '').split('\n');
        
        let i = 0;
        while (i < lines.length) {
            // Find the start of a block by looking for a line with a timestamp
            if (lines[i] && lines[i].includes('-->')) {
                const timestampLine = lines[i];
                const textLines = [];
                let j = i + 1; // Start looking for text on the next line
                
                // Collect text lines until we hit a blank line or a new timestamp
                while(j < lines.length && lines[j].trim() !== '' && !lines[j].includes('-->')) {
                    // Check if the line is just a number (a stray index) and ignore it
                    if (!lines[j].match(/^\d+$/)) {
                        textLines.push(lines[j]);
                    }
                    j++;
                }
                
                const [startStr, endStr] = timestampLine.split(' --> ');
                if (startStr && endStr) {
                    subs.push({
                        start: srtTimeToSeconds(startStr.trim()),
                        end: srtTimeToSeconds(endStr.trim()),
                        text: textLines.join('<br>')
                    });
                }
                i = j; // Move the main index to where we left off
            } else {
                i++; // Not a timestamp line, move to the next line
            }
        }
        return subs;
    }
    
    function srtTimeToSeconds(timeStr) {
        const [hms, ms] = timeStr.split(',');
        const [h, m, s] = hms.split(':');
        return parseInt(h) * 3600 + parseInt(m) * 60 + parseInt(s) + parseInt(ms) / 1000;
    }

    // --- Event Listeners ---
    lang1Select.addEventListener('change', handleLanguageChange);
    lang2Select.addEventListener('change', handleLanguageChange);
    player.addEventListener('timeupdate', syncLyrics);

    loopToggleBtn.addEventListener('click', () => {
        isLooping = !isLooping;
        loopToggleBtn.classList.toggle('active', isLooping);
    });

    lyricsPane.addEventListener('click', async function(event) {
        if (event.target.classList.contains('clickable-word')) {
            const clickedWord = event.target.dataset.word;
            const fullSentence = event.target.parentElement.textContent.trim();
            const langCode = event.target.parentElement.dataset.lang;

            const originalHtml = event.target.parentElement.innerHTML.replace(
                `<span class="clickable-word" data-word="${clickedWord}">${event.target.textContent}</span>`,
                `<mark>${event.target.textContent}</mark>`
            );
            document.getElementById('popup-original-sentence').innerHTML = originalHtml;
            document.getElementById('popup-translated-sentence').textContent = 'Translating sentence...';
            document.getElementById('popup-word-translation').textContent = 'Translating word...';
            popup.classList.remove('popup-hidden');

            try {
                const response = await fetch('/get_definition', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ word: clickedWord, sentence: fullSentence, lang_code: langCode }),
                });

                if (!response.ok) throw new Error('Translation failed');
                
                const data = await response.json();

                document.getElementById('popup-translated-sentence').innerHTML = data.sentence_translation;
                document.getElementById('popup-word-translation').innerHTML = 
                    `${clickedWord} <span>-></span> ${data.word_translation}`;
                
                popup.dataset.word = clickedWord;
                popup.dataset.definition = data.word_translation;
                popup.dataset.context = fullSentence;

            } catch (error) {
                document.getElementById('popup-translated-sentence').textContent = 'Could not translate this line.';
                document.getElementById('popup-word-translation').textContent = '';
            }
        }
    });

    popupCloseBtn.addEventListener('click', () => popup.classList.add('popup-hidden'));
    
    popupSaveBtn.addEventListener('click', async () => {
        const { word, definition, context } = popup.dataset;

        if (!definition || definition.includes('...')) {
            alert("Cannot save, no definition found.");
            return;
        }

        try {
            const response = await fetch('/save_word', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ word, definition, context }),
            });
            const result = await response.json();
            alert(result.message);
        } catch (error) {
            alert('Failed to save word.');
        }
    });

    handleLanguageChange();

    document.addEventListener('keydown', function(event) {
    const key = event.key.toLowerCase();

    switch (key) {
        case ' ':
            if (document.activeElement !== player) {
                event.preventDefault();
                player.paused ? player.play() : player.pause();
            }
            break;


        case 'arrowleft': // ← — rewind 5s
            player.currentTime = Math.max(player.currentTime - 5, 0);
            break;

        case 'arrowright': // → — forward 5s
            player.currentTime = Math.min(player.currentTime + 5, player.duration);
            break;

        case 'l': // L — loop toggle
            isLooping = !isLooping;
            loopToggleBtn.classList.toggle('active', isLooping);
            break;

        case 'f': // F — fullscreen toggle
            if (document.fullscreenElement) {
                document.exitFullscreen();
            } else {
                player.requestFullscreen();
            }
            break;

        case 'm': // M — mute toggle
            player.muted = !player.muted;
            break;
    }
});
});