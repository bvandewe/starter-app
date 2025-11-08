/**
 * Tasks UI Module
 * Handles rendering and interaction of task UI components
 */

import * as bootstrap from 'bootstrap';
import {
    fetchTasks,
    createTask as createTaskAPI,
    deleteTask as deleteTaskAPI,
} from '../api/tasks.js';

/**
 * Get current user roles from user info
 * @returns {Array<string>} - Array of user roles
 */
function getCurrentUserRoles() {
    // Get user info from the navbar (set during login)
    const userInfoElement = document.getElementById('user-info');
    const userText = userInfoElement?.textContent || '';

    // User info is stored in localStorage during authentication
    const rolesJson = localStorage.getItem('user_roles');
    if (rolesJson) {
        try {
            return JSON.parse(rolesJson);
        } catch {
            return [];
        }
    }

    return [];
}

/**
 * Check if user can delete tasks (admin or manager role)
 * @returns {boolean}
 */
function canDeleteTasks() {
    const roles = getCurrentUserRoles();
    return roles.includes('admin') || roles.includes('manager');
}

/**
 * Handle task deletion
 * @param {string} taskId - Task ID to delete
 */
async function handleDeleteTask(taskId) {
    if (!confirm('Are you sure you want to delete this task?')) {
        return;
    }

    try {
        await deleteTaskAPI(taskId);
        // Reload tasks to refresh the list
        await loadTasks();
    } catch (error) {
        alert('Failed to delete task: ' + error.message);
    }
}

/**
 * Render tasks to the DOM
 * @param {Array} tasks - Array of task objects
 */
export function renderTasks(tasks) {
    const container = document.getElementById('tasks-container');
    container.innerHTML = '';

    if (tasks.length === 0) {
        container.innerHTML = '<div class="col"><p class="text-muted">No tasks found.</p></div>';
        return;
    }

    const showDeleteButton = canDeleteTasks();

    tasks.forEach(task => {
        const priorityBadge =
            {
                low: 'success',
                medium: 'warning',
                high: 'danger',
            }[task.priority] || 'secondary';

        const statusBadge =
            {
                pending: 'secondary',
                in_progress: 'info',
                completed: 'success',
            }[task.status] || 'secondary';

        // Create delete button HTML if user has permission
        const deleteButtonHtml = showDeleteButton
            ? `<button class="btn btn-sm btn-danger delete-task-btn" data-task-id="${task.id}">
                   <i class="bi bi-trash"></i> Delete
               </button>`
            : '';

        const taskCard = `
            <div class="col-md-4 mb-3">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">${task.title}</h5>
                        <p class="card-text">${task.description}</p>
                        <div class="mb-2">
                            <span class="badge bg-${priorityBadge}">${task.priority}</span>
                            <span class="badge bg-${statusBadge}">${task.status}</span>
                        </div>
                        <small class="text-muted">Created: ${new Date(
                            task.created_at
                        ).toLocaleDateString()}</small>
                        ${deleteButtonHtml ? `<div class="mt-2">${deleteButtonHtml}</div>` : ''}
                    </div>
                </div>
            </div>
        `;

        container.innerHTML += taskCard;
    });

    // Attach event listeners to delete buttons
    if (showDeleteButton) {
        document.querySelectorAll('.delete-task-btn').forEach(button => {
            button.addEventListener('click', e => {
                const taskId = e.currentTarget.getAttribute('data-task-id');
                handleDeleteTask(taskId);
            });
        });
    }
}

/**
 * Load and render tasks
 */
export async function loadTasks() {
    try {
        const tasks = await fetchTasks();
        renderTasks(tasks);
    } catch (error) {
        console.error('Failed to load tasks:', error);
        const container = document.getElementById('tasks-container');
        container.innerHTML =
            '<div class="col"><p class="text-danger">Failed to load tasks. Please try again.</p></div>';
    }
}

/**
 * Handle create task form submission
 */
export async function handleCreateTask() {
    const title = document.getElementById('task-title').value;
    const description = document.getElementById('task-description').value;
    const priority = document.getElementById('task-priority').value;

    try {
        await createTaskAPI({ title, description, priority });

        // Close modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('createTaskModal'));
        modal.hide();

        // Reset form
        document.getElementById('create-task-form').reset();

        // Reload tasks
        await loadTasks();
    } catch (error) {
        alert('Failed to create task: ' + error.message);
    }
}
